#!/usr/bin/env python3
"""Manual, exact live containment coordination for Guardian V1."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from typing import Any, Mapping

from guardian_causal_projection import project_security_causality
from guardian_causality import CausalGraph, CausalNode, file_process_edge, package_file_edge
from guardian_containment import (
    ContainmentAuthority,
    ContainmentTarget,
    ProcessIdentity,
    plan_containment,
)
from guardian_containment_adapter import (
    ContainmentReceipt,
    ExactProcessContainmentDriver,
    execute_containment,
    release_containment,
)
from guardian_evidence import parse_timestamp, utc_stamp
from guardian_explain import describe_security
from security_containment import process_executable_identity, process_start_ticks
from security_probe import normalized_package_paths, package_record, read_process

SCHEMA_VERSION = 1
DEFAULT_AUTHORITY_SECONDS = 60
DEFAULT_POLL_SECONDS = 5.0
ACTIVE_STATES = {
    "proposed",
    "authorization-required",
    "containing",
    "contained",
    "releasing",
    "verification-failed",
}
_STATE_PRIORITY = {
    "verification-failed": 6,
    "contained": 5,
    "containing": 4,
    "releasing": 4,
    "authorization-required": 3,
    "proposed": 2,
    "none": 0,
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _atomic_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _root(state_root: Path) -> Path:
    return state_root / "guardian" / "live-response"


def _active_path(state_root: Path, incident_id: str) -> Path:
    return _root(state_root) / "active" / f"{incident_id}.json"


def _authority_path(state_root: Path, authority_id: str) -> Path:
    return _root(state_root) / "authorizations" / f"{authority_id}.json"


def _receipt_path(state_root: Path, receipt_id: str) -> Path:
    return _root(state_root) / "receipts" / f"{receipt_id}.json"


def _claim_authority(state_root: Path, authority_id: str, action: str) -> bool:
    path = _root(state_root) / "authorizations" / "consumed" / f"{authority_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-response-authority-consumption",
        "authority_id": authority_id,
        "action": action,
        "consumed_at": utc_stamp(datetime.now(timezone.utc)),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        offset = 0
        while offset < len(data):
            offset += os.write(fd, data[offset:])
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def _history(state_root: Path, event: str, payload: Mapping[str, Any]) -> None:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    name = f"{stamp}-{event}-{secrets.token_hex(3)}.json"
    _atomic_private(_root(state_root) / "history" / name, {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-response-history",
        "event": event,
        "recorded_at": utc_stamp(datetime.now(timezone.utc)),
        "payload": dict(payload),
    })


def _archive_active(state_root: Path, incident_id: str, reason: str) -> None:
    path = _active_path(state_root, incident_id)
    row = _read_object(path)
    if row is None:
        return
    _history(state_root, reason, row)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _source_incident(state_root: Path, incident_id: str) -> dict[str, Any] | None:
    return _read_object(state_root / "incidents" / "active" / f"{incident_id}.json")


def _guardian_assessment(state_root: Path, incident_id: str) -> dict[str, Any] | None:
    return _read_object(state_root / "guardian" / "active" / f"{incident_id}.json")

def _confirmed_finding(incident: Mapping[str, Any]) -> tuple[str, str] | None:
    rows = incident.get("signals")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, Mapping) or row.get("kind") != "confirmed-finding":
            continue
        details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
        finding_id = details.get("finding_id") or details.get("id")
        version = details.get("installed_version")
        if isinstance(finding_id, str) and finding_id and isinstance(version, str) and version:
            return finding_id, version
    return None


def _incident_pids(incident: Mapping[str, Any]) -> tuple[int, ...]:
    raw = incident.get("runtime_pids")
    if not isinstance(raw, list):
        return ()
    values = []
    for value in raw:
        if isinstance(value, int) and not isinstance(value, bool) and value > 1:
            values.append(value)
    return tuple(sorted(set(values)))

def _base_process_pids(graph: CausalGraph) -> set[int]:
    result: set[int] = set()
    for node in graph.nodes:
        if node.kind != "process":
            continue
        pid = node.attributes.get("pid")
        if isinstance(pid, int):
            result.add(pid)
    return result


def _exact_identities(
    incident: Mapping[str, Any],
    *,
    db_root: Path,
    proc_root: Path,
    fs_root: Path,
    uid: int,
) -> tuple[dict[str, Any] | None, tuple[ProcessIdentity, ...], str | None]:
    subject = incident.get("subject") if isinstance(incident.get("subject"), Mapping) else {}
    package = subject.get("id") if subject.get("type") == "package" else None
    if not isinstance(package, str) or not package:
        return None, (), "incident-subject-not-exact-package"
    record = package_record(db_root, package)
    if record is None:
        return None, (), "package-record-unavailable"
    finding = _confirmed_finding(incident)
    if finding is None:
        return record, (), "confirmed-finding-unavailable"
    _finding_id, finding_version = finding
    if record.get("version") != finding_version:
        return record, (), "package-version-changed"
    pids = _incident_pids(incident)
    if not pids:
        return record, (), "incident-has-no-runtime-target"
    package_paths = normalized_package_paths(record)
    identities: list[ProcessIdentity] = []
    missing = 0
    for pid in pids:
        current = read_process(proc_root / str(pid), fs_root)
        if current is None:
            missing += 1
            continue
        if current.get("uid") != uid:
            return record, (), "target-uid-mismatch"
        if current.get("relative_exe") not in package_paths:
            return record, (), "target-package-ownership-mismatch"
        exe = current.get("exe")
        if not isinstance(exe, str) or not exe.startswith("/") or exe.endswith(" (deleted)"):
            return record, (), "target-executable-not-stable"
        start = process_start_ticks(proc_root, pid)
        executable_identity = process_executable_identity(proc_root, pid)
        if start is None or executable_identity is None:
            return record, (), "target-process-identity-incomplete"
        identities.append(ProcessIdentity(pid, start, exe, executable_identity))
    if not identities and missing:
        return record, (), "target-no-longer-running"
    return record, tuple(sorted(identities)), None


def _augment_graph(
    incident: Mapping[str, Any],
    base: CausalGraph,
    identities: tuple[ProcessIdentity, ...],
    package_record_value: Mapping[str, Any],
) -> tuple[CausalGraph | None, tuple[str, ...], str | None]:
    subject = incident.get("subject") if isinstance(incident.get("subject"), Mapping) else {}
    package = str(subject.get("id") or "")
    subject_id = f"subject:package:{package}"
    subject_node = next((node for node in base.nodes if node.node_id == subject_id), None)
    if subject_node is None:
        return None, (), "causal-package-subject-missing"
    observed_pids = _base_process_pids(base)
    if any(identity.pid not in observed_pids for identity in identities):
        return None, (), "causal-process-evidence-missing"

    nodes = {node.node_id: node for node in base.nodes}
    edges = {edge.edge_id: edge for edge in base.edges}
    proof_edges: list[str] = []
    package_evidence = "package-record:" + _digest({
        "name": package_record_value.get("name"),
        "version": package_record_value.get("version"),
        "files": sorted(package_record_value.get("files") or []),
    })
    for identity in identities:
        file_node = CausalNode(
            f"file:{identity.exe}",
            "file",
            identity.exe,
            (package_evidence,),
            {"package": package},
        )
        nodes.setdefault(file_node.node_id, file_node)
        ownership = package_file_edge(
            subject_node,
            nodes[file_node.node_id],
            package_identity=package,
            observed_package=package,
            file_path=identity.exe,
            evidence_id=package_evidence,
        )
        edges.setdefault(ownership.edge_id, ownership)
        process_evidence = (
            f"proc-start:{identity.pid}:{identity.start_time_ticks}",
            f"proc-exe:{identity.pid}:{identity.exe_identity}",
        )
        stable = CausalNode(
            f"process:stable:{identity.pid}:{identity.start_time_ticks}:{identity.exe_identity}",
            "process",
            f"pid={identity.pid}",
            process_evidence,
            {
                "pid": identity.pid,
                "exe": identity.exe,
                "start_time_ticks": identity.start_time_ticks,
                "exe_identity": identity.exe_identity,
                "stable_identity": True,
            },
        )
        nodes[stable.node_id] = stable
        execution = file_process_edge(
            nodes[file_node.node_id],
            stable,
            file_path=identity.exe,
            process_exe=identity.exe,
            executable_identity_verified=True,
            process_identity_stable=True,
            evidence_ids=process_evidence,
        )
        edges[execution.edge_id] = execution
        if ownership.strength.value != "proven" or execution.strength.value != "proven":
            return None, (), "exact-process-causality-not-proven"
        proof_edges.extend((ownership.edge_id, execution.edge_id))
    return CausalGraph(
        tuple(sorted(nodes.values(), key=lambda item: item.node_id)),
        tuple(sorted(edges.values(), key=lambda item: item.edge_id)),
    ), tuple(sorted(set(proof_edges))), None


def plan_incident(
    state_root: Path,
    incident_id: str,
    *,
    db_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source = _source_incident(state_root, incident_id)
    assessment = _guardian_assessment(state_root, incident_id)
    if source is None or assessment is None:
        return {"state": "none", "incident_id": incident_id, "reason": "active-incident-unavailable"}
    if source.get("status") not in {None, "active"} or assessment.get("status") != "active":
        return {"state": "none", "incident_id": incident_id, "reason": "incident-not-active"}
    if source.get("containment_eligible") is not True or source.get("response_reversible") is not True:
        return {"state": "none", "incident_id": incident_id, "reason": "incident-not-containment-eligible"}
    if source.get("confidence") != "confirmed":
        return {"state": "none", "incident_id": incident_id, "reason": "incident-not-confirmed"}

    base = project_security_causality((source,))
    record, identities, identity_error = _exact_identities(
        source,
        db_root=db_root,
        proc_root=proc_root,
        fs_root=fs_root,
        uid=os.getuid() if uid is None else uid,
    )
    if identity_error is not None or record is None:
        return {"state": "none", "incident_id": incident_id, "reason": identity_error or "target-unavailable"}
    graph, proof_edges, graph_error = _augment_graph(source, base, identities, record)
    if graph_error is not None or graph is None:
        return {"state": "none", "incident_id": incident_id, "reason": graph_error or "causal-proof-unavailable"}

    finding = _confirmed_finding(source)
    assert finding is not None
    finding_id, version = finding
    subject = source.get("subject") if isinstance(source.get("subject"), Mapping) else {}
    target = ContainmentTarget(str(subject["id"]), version, finding_id, identities)
    graph_payload = graph.as_dict()
    graph_digest = _digest(graph_payload)
    source_digest = _digest(source)
    assessment_digest = _digest(assessment)
    evidence_digest = _digest({
        "incident": source_digest,
        "assessment": assessment_digest,
        "proof_edges": proof_edges,
        "graph": graph_digest,
    })
    process_identity_digest = _digest([asdict(item) for item in identities])
    proposal_material = {
        "incident_id": incident_id,
        "evidence_digest": evidence_digest,
        "graph_digest": graph_digest,
        "target_digest": target.digest,
        "process_identity_digest": process_identity_digest,
    }
    proposal_id = "proposal-" + _digest(proposal_material)[:24]
    explained = describe_security(source)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-response",
        "state": "authorization-required",
        "incident_id": incident_id,
        "proposal_id": proposal_id,
        "captured_at": utc_stamp(current),
        "source_incident_digest": source_digest,
        "guardian_assessment_digest": assessment_digest,
        "evidence_digest": evidence_digest,
        "graph_digest": graph_digest,
        "target_digest": target.digest,
        "process_identity_digest": process_identity_digest,
        "proof_edge_ids": list(proof_edges),
        "causal_graph": graph_payload,
        "target": target.canonical(),
        "explanation": {
            "what_happened": list(explained.get("happened") or []),
            "evidence": list(explained.get("details") or []),
            "why": list(explained.get("why") or []),
            "proposed_action": "isolate this exact process target",
            "unaffected": "processes outside the exact target are not selected",
            "unresolved": "Guardian host trust/self-health is not elevated by this proposal",
            "authorization": "required",
        },
        "authorization_required": True,
        "automatic_authority": False,
    }


def _parse_target(payload: Mapping[str, Any]) -> ContainmentTarget:
    rows = payload.get("processes")
    if not isinstance(rows, list):
        raise ValueError("target processes missing")
    identities = tuple(
        ProcessIdentity(
            int(row["pid"]),
            int(row["start_time_ticks"]),
            str(row["exe"]),
            str(row["exe_identity"]) if row.get("exe_identity") is not None else None,
        )
        for row in rows
        if isinstance(row, Mapping)
    )
    return ContainmentTarget(
        str(payload["package"]),
        str(payload["version"]),
        str(payload["finding_id"]),
        identities,
    )


def reconcile(
    state_root: Path,
    *,
    db_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
) -> dict[str, Any]:
    active_source = state_root / "incidents" / "active"
    incident_ids = (
        {path.stem for path in active_source.glob("inc-*.json")}
        if active_source.is_dir()
        else set()
    )
    response_active = _root(state_root) / "active"
    existing_ids = (
        {path.stem for path in response_active.glob("inc-*.json")}
        if response_active.is_dir()
        else set()
    )
    results: list[dict[str, Any]] = []
    for incident_id in sorted(incident_ids):
        existing = _read_object(_active_path(state_root, incident_id))
        if existing and existing.get("state") in {
            "containing", "contained", "releasing", "verification-failed"
        }:
            results.append(existing)
            continue
        proposal = plan_incident(
            state_root,
            incident_id,
            db_root=db_root,
            proc_root=proc_root,
            fs_root=fs_root,
            uid=uid,
        )
        if proposal.get("state") != "authorization-required":
            if existing is not None:
                _archive_active(state_root, incident_id, "proposal-no-longer-applicable")
            continue
        if existing is None or existing.get("proposal_id") != proposal.get("proposal_id"):
            if existing is not None:
                _archive_active(state_root, incident_id, "proposal-superseded")
            _history(state_root, "proposed", {**proposal, "state": "proposed"})
            _atomic_private(_active_path(state_root, incident_id), proposal)
            _history(state_root, "authorization-required", proposal)
        results.append(proposal)
    for incident_id in sorted(existing_ids - incident_ids):
        existing = _read_object(_active_path(state_root, incident_id))
        if existing and existing.get("state") in {"contained", "releasing", "verification-failed"}:
            results.append(existing)
        else:
            _archive_active(state_root, incident_id, "incident-cleared-before-containment")
    return {"state": containment_status(state_root)["state"], "active": results}


def containment_status(state_root: Path) -> dict[str, Any]:
    active_dir = _root(state_root) / "active"
    rows: list[dict[str, Any]] = []
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("inc-*.json")):
            row = _read_object(path)
            if row is None or row.get("state") not in ACTIVE_STATES:
                continue
            rows.append({
                "incident_id": row.get("incident_id"),
                "proposal_id": row.get("proposal_id"),
                "state": row.get("state"),
                "target_digest": row.get("target_digest"),
                "receipt_id": row.get("receipt_id"),
                "reason": row.get("reason"),
            })
    state = max(
        (str(row["state"]) for row in rows),
        key=lambda value: _STATE_PRIORITY.get(value, 0),
        default="none",
    )
    return {
        "state": state,
        "active": rows,
        "automatic_authority": False,
        "history_retained": True,
    }


def _authorization(
    state_root: Path,
    *,
    action: str,
    record: Mapping[str, Any],
    confirm: str,
    ttl_seconds: int,
) -> dict[str, Any]:
    if action == "contain":
        expected = f"AUTHORIZE-CONTAIN:{record.get('proposal_id')}"
    else:
        expected = f"AUTHORIZE-RELEASE:{record.get('receipt_id')}"
    if confirm != expected:
        return {"result": "denied", "reason": "explicit-authorization-token-mismatch"}
    now = datetime.now(timezone.utc)
    ttl = min(max(int(ttl_seconds), 1), 300)
    authority_id = "auth-" + secrets.token_hex(12)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-response-authorization",
        "authority_id": authority_id,
        "action": action,
        "user_authorized": True,
        "incident_id": record.get("incident_id"),
        "proposal_id": record.get("proposal_id"),
        "receipt_id": record.get("receipt_id"),
        "issued_at": utc_stamp(now),
        "expires_at": utc_stamp(now + timedelta(seconds=ttl)),
        "evidence_digest": record.get("evidence_digest"),
        "graph_digest": record.get("graph_digest"),
        "target_digest": record.get("target_digest"),
        "process_identity_digest": record.get("process_identity_digest"),
        "receipt_digest": record.get("receipt_digest"),
        "target": record.get("target"),
    }
    _atomic_private(_authority_path(state_root, authority_id), payload)
    _history(state_root, f"{action}-authorized", payload)
    return payload


def authorize_containment(
    state_root: Path,
    incident_id: str,
    proposal_id: str,
    *,
    confirm: str,
    ttl_seconds: int = DEFAULT_AUTHORITY_SECONDS,
) -> dict[str, Any]:
    record = _read_object(_active_path(state_root, incident_id))
    if record is None or record.get("state") != "authorization-required":
        return {"result": "refused", "reason": "proposal-not-active"}
    if record.get("proposal_id") != proposal_id:
        return {"result": "refused", "reason": "proposal-id-mismatch"}
    return _authorization(
        state_root,
        action="contain",
        record=record,
        confirm=confirm,
        ttl_seconds=ttl_seconds,
    )


def _authority_current(authority: Mapping[str, Any], action: str) -> str | None:
    if authority.get("user_authorized") is not True or authority.get("action") != action:
        return "authorization-action-mismatch"
    try:
        expires = parse_timestamp(str(authority.get("expires_at")))
        issued = parse_timestamp(str(authority.get("issued_at")))
    except ValueError:
        return "authorization-window-invalid"
    now = datetime.now(timezone.utc)
    if issued is None or expires is None or now < issued or now > expires:
        return "authorization-expired"
    return None


def _authority_target_consistent(authority: Mapping[str, Any]) -> bool:
    target_payload = authority.get("target")
    if not isinstance(target_payload, Mapping):
        return False
    try:
        target = _parse_target(target_payload)
    except (KeyError, TypeError, ValueError):
        return False
    identities_digest = _digest([asdict(item) for item in target.processes])
    return (
        target.digest == authority.get("target_digest")
        and identities_digest == authority.get("process_identity_digest")
    )


def _same_binding(authority: Mapping[str, Any], proposal: Mapping[str, Any]) -> bool:
    keys = (
        "incident_id",
        "proposal_id",
        "evidence_digest",
        "graph_digest",
        "target_digest",
        "process_identity_digest",
    )
    return (
        _authority_target_consistent(authority)
        and all(authority.get(key) == proposal.get(key) for key in keys)
    )


def _driver(
    *,
    state_root: Path,
    db_root: Path,
    proc_root: Path,
    fs_root: Path,
    uid: int,
) -> ExactProcessContainmentDriver:
    return ExactProcessContainmentDriver(
        db_root=db_root,
        proc_root=proc_root,
        fs_root=fs_root,
        state_root=state_root,
        uid=uid,
    )


def execute_authorized(
    state_root: Path,
    authority_id: str,
    *,
    db_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
) -> dict[str, Any]:
    authority = _read_object(_authority_path(state_root, authority_id))
    if authority is None:
        return {"result": "refused", "reason": "authorization-unavailable"}
    authority_error = _authority_current(authority, "contain")
    if authority_error is not None:
        return {"result": "refused", "reason": authority_error}
    incident_id = str(authority.get("incident_id") or "")
    active = _read_object(_active_path(state_root, incident_id))
    if (
        active is None
        or active.get("state") != "authorization-required"
        or active.get("proposal_id") != authority.get("proposal_id")
    ):
        return {"result": "refused", "reason": "authorization-proposal-not-active"}
    proposal = plan_incident(
        state_root,
        incident_id,
        db_root=db_root,
        proc_root=proc_root,
        fs_root=fs_root,
        uid=uid,
    )
    if proposal.get("state") == "none" and proposal.get("reason") == "target-no-longer-running":
        _archive_active(state_root, incident_id, "containment-no-longer-applicable")
        result = {
            "result": "no-longer-applicable",
            "verified": True,
            "incident_id": incident_id,
        }
        _history(state_root, "containment-no-longer-applicable", result)
        return result
    if proposal.get("state") != "authorization-required" or not _same_binding(authority, proposal):
        result = {
            "result": "refused",
            "reason": "authorization-binding-changed",
            "incident_id": incident_id,
        }
        _history(state_root, "containment-authority-invalid", result)
        return result

    if not _claim_authority(state_root, authority_id, "contain"):
        return {"result": "refused", "reason": "authorization-already-consumed"}
    target = _parse_target(proposal["target"])
    low = ContainmentAuthority(
        authority_id=authority_id,
        issuer="guardian-live-response:user-confirmation",
        verified=True,
        issued_at=str(authority["issued_at"]),
        expires_at=str(authority["expires_at"]),
        target_digest=target.digest,
        evidence_ids=(
            str(proposal["incident_id"]),
            str(proposal["evidence_digest"]),
            str(proposal["graph_digest"]),
            str(proposal["proposal_id"]),
        ),
        reversible=True,
    )
    plan = plan_containment(target, low)
    active = {
        **proposal,
        "state": "containing",
        "authority_id": authority_id,
    }
    _atomic_private(_active_path(state_root, incident_id), active)
    _history(state_root, "containing", active)
    driver = _driver(
        state_root=state_root,
        db_root=db_root,
        proc_root=proc_root,
        fs_root=fs_root,
        uid=os.getuid() if uid is None else uid,
    )
    receipt = execute_containment(plan, driver)
    receipt_payload = receipt.as_dict()
    receipt_id = "receipt-" + _digest({
        "authority_id": authority_id,
        "target_digest": target.digest,
        "session_id": receipt.session_id,
        "result": receipt.result,
    })[:24]
    wrapped = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-response-receipt",
        "receipt_id": receipt_id,
        "incident_id": incident_id,
        "proposal_id": proposal["proposal_id"],
        "target": proposal["target"],
        "process_identity_digest": proposal["process_identity_digest"],
        "receipt": receipt_payload,
    }
    wrapped["receipt_digest"] = _digest(wrapped)
    _atomic_private(_receipt_path(state_root, receipt_id), wrapped)
    if receipt.verified and receipt.result == "contained":
        final = {
            **proposal,
            "state": "contained",
            "authority_id": authority_id,
            "receipt_id": receipt_id,
            "receipt_digest": wrapped["receipt_digest"],
            "receipt": receipt_payload,
        }
        _atomic_private(_active_path(state_root, incident_id), final)
        _history(state_root, "contained", final)
        return {
            "result": "contained",
            "verified": True,
            "receipt_id": receipt_id,
            "incident_id": incident_id,
        }
    failed = {
        **proposal,
        "state": "verification-failed",
        "authority_id": authority_id,
        "receipt_id": receipt_id,
        "receipt_digest": wrapped["receipt_digest"],
        "receipt": receipt_payload,
        "reason": receipt.reason,
    }
    _atomic_private(_active_path(state_root, incident_id), failed)
    _history(state_root, "containment-verification-failed", failed)
    return {
        "result": "verification-failed",
        "verified": False,
        "receipt_id": receipt_id,
        "incident_id": incident_id,
    }


def authorize_release(
    state_root: Path,
    incident_id: str,
    receipt_id: str,
    *,
    confirm: str,
    ttl_seconds: int = DEFAULT_AUTHORITY_SECONDS,
) -> dict[str, Any]:
    record = _read_object(_active_path(state_root, incident_id))
    if record is None or record.get("state") != "contained":
        return {"result": "refused", "reason": "contained-response-not-active"}
    if record.get("receipt_id") != receipt_id:
        return {"result": "refused", "reason": "receipt-id-mismatch"}
    return _authorization(
        state_root,
        action="release",
        record=record,
        confirm=confirm,
        ttl_seconds=ttl_seconds,
    )


def _receipt_from_payload(payload: Mapping[str, Any]) -> ContainmentReceipt:
    return ContainmentReceipt(
        result=str(payload.get("result") or ""),
        authority_id=str(payload["authority_id"]) if payload.get("authority_id") is not None else None,
        target_digest=str(payload.get("target_digest") or ""),
        session_id=str(payload["session_id"]) if payload.get("session_id") is not None else None,
        contained=tuple(
            ProcessIdentity(
                int(row["pid"]),
                int(row["start_time_ticks"]),
                str(row["exe"]),
                str(row["exe_identity"]) if row.get("exe_identity") is not None else None,
            )
            for row in payload.get("contained") or []
            if isinstance(row, Mapping)
        ),
        failed=tuple(
            dict(row)
            for row in payload.get("failed") or []
            if isinstance(row, Mapping)
        ),
        rollback=dict(payload.get("rollback") or {}),
        verified=payload.get("verified") is True,
        reason=str(payload.get("reason") or ""),
    )


def execute_release(
    state_root: Path,
    authority_id: str,
    *,
    db_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
) -> dict[str, Any]:
    authority = _read_object(_authority_path(state_root, authority_id))
    if authority is None:
        return {"result": "refused", "reason": "authorization-unavailable"}
    authority_error = _authority_current(authority, "release")
    if authority_error is not None:
        return {"result": "refused", "reason": authority_error}
    incident_id = str(authority.get("incident_id") or "")
    active = _read_object(_active_path(state_root, incident_id))
    if active is None or active.get("state") != "contained":
        return {"result": "refused", "reason": "contained-response-not-active"}
    keys = (
        "incident_id",
        "proposal_id",
        "receipt_id",
        "receipt_digest",
        "target_digest",
        "process_identity_digest",
    )
    if (
        not _authority_target_consistent(authority)
        or any(active.get(key) != authority.get(key) for key in keys)
    ):
        return {"result": "refused", "reason": "release-authorization-binding-changed"}

    receipt_row = _read_object(
        _receipt_path(state_root, str(active.get("receipt_id") or ""))
    )
    if receipt_row is None:
        return {"result": "refused", "reason": "receipt-unavailable"}
    stored_digest = receipt_row.get("receipt_digest")
    digest_payload = {key: value for key, value in receipt_row.items() if key != "receipt_digest"}
    if _digest(digest_payload) != stored_digest:
        return {"result": "refused", "reason": "receipt-integrity-invalid"}
    if stored_digest != active.get("receipt_digest"):
        return {"result": "refused", "reason": "receipt-digest-mismatch"}
    if not _claim_authority(state_root, authority_id, "release"):
        return {"result": "refused", "reason": "authorization-already-consumed"}
    target = _parse_target(active["target"])

    missing = [
        identity
        for identity in target.processes
        if not (proc_root / str(identity.pid)).exists()
    ]
    if len(missing) == len(target.processes):
        result = {
            "result": "no-longer-applicable",
            "verified": True,
            "incident_id": incident_id,
        }
        _archive_active(state_root, incident_id, "release-no-longer-applicable")
        _history(state_root, "release-no-longer-applicable", result)
        return result

    releasing = {
        **active,
        "state": "releasing",
        "release_authority_id": authority_id,
    }
    _atomic_private(_active_path(state_root, incident_id), releasing)
    _history(state_root, "releasing", releasing)
    driver = _driver(
        state_root=state_root,
        db_root=db_root,
        proc_root=proc_root,
        fs_root=fs_root,
        uid=os.getuid() if uid is None else uid,
    )
    receipt_payload = receipt_row.get("receipt")
    receipt = _receipt_from_payload(
        receipt_payload if isinstance(receipt_payload, Mapping) else {}
    )
    result = release_containment(receipt, target, driver)
    released = result.get("released") if isinstance(result.get("released"), list) else []
    if result.get("result") == "released" and len(released) == len(target.processes):
        _history(
            state_root,
            "released",
            {**releasing, "release_result": result},
        )
        try:
            _active_path(state_root, incident_id).unlink()
        except FileNotFoundError:
            pass
        return {
            "result": "released",
            "verified": True,
            "incident_id": incident_id,
        }
    failed = {
        **active,
        "state": "verification-failed",
        "reason": "release-verification-failed",
        "release_result": result,
    }
    _atomic_private(_active_path(state_root, incident_id), failed)
    _history(state_root, "release-verification-failed", failed)
    return {
        "result": "verification-failed",
        "verified": False,
        "incident_id": incident_id,
        "detail": result,
    }


def response_loop(
    state_root: Path,
    *,
    interval: float = DEFAULT_POLL_SECONDS,
    db_root: Path | None = None,
    proc_root: Path | None = None,
    fs_root: Path | None = None,
) -> None:
    delay = max(1.0, float(interval))
    db = db_root or Path(os.environ.get("MAHO_PACMAN_DB_ROOT", "/var/lib/pacman/local"))
    proc = proc_root or Path(os.environ.get("MAHO_PROC_ROOT", "/proc"))
    fs = fs_root or Path(os.environ.get("MAHO_FS_ROOT", "/"))
    while True:
        try:
            reconcile(
                state_root,
                db_root=db,
                proc_root=proc,
                fs_root=fs,
                uid=os.getuid(),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            _history(
                state_root,
                "coordinator-error",
                {"error": f"{type(exc).__name__}:{exc}"},
            )
        time.sleep(delay)


def _paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path, int]:
    state = Path(args.state_root)
    db = Path(args.db_root)
    proc = Path(args.proc_root)
    fs = Path(args.fs_root)
    uid = args.uid if args.uid is not None else os.getuid()
    return state, db, proc, fs, uid


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian-live-response")
    parser.add_argument(
        "--state-root",
        default=str(
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
            / "maho/security"
        ),
    )
    parser.add_argument(
        "--db-root",
        default=os.environ.get("MAHO_PACMAN_DB_ROOT", "/var/lib/pacman/local"),
    )
    parser.add_argument(
        "--proc-root",
        default=os.environ.get("MAHO_PROC_ROOT", "/proc"),
    )
    parser.add_argument(
        "--fs-root",
        default=os.environ.get("MAHO_FS_ROOT", "/"),
    )
    parser.add_argument("--uid", type=int)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("reconcile")
    sub.add_parser("status")
    plan = sub.add_parser("plan")
    plan.add_argument("incident_id")
    auth = sub.add_parser("authorize")
    auth.add_argument("incident_id")
    auth.add_argument("proposal_id")
    auth.add_argument("--confirm", required=True)
    auth.add_argument("--ttl", type=int, default=DEFAULT_AUTHORITY_SECONDS)
    execute = sub.add_parser("execute")
    execute.add_argument("authority_id")
    release_auth = sub.add_parser("authorize-release")
    release_auth.add_argument("incident_id")
    release_auth.add_argument("receipt_id")
    release_auth.add_argument("--confirm", required=True)
    release_auth.add_argument("--ttl", type=int, default=DEFAULT_AUTHORITY_SECONDS)
    release = sub.add_parser("release")
    release.add_argument("authority_id")
    args = parser.parse_args(argv)
    state, db, proc, fs, uid = _paths(args)
    if args.command == "reconcile":
        result = reconcile(
            state,
            db_root=db,
            proc_root=proc,
            fs_root=fs,
            uid=uid,
        )
    elif args.command == "status":
        result = containment_status(state)
    elif args.command == "plan":
        result = plan_incident(
            state,
            args.incident_id,
            db_root=db,
            proc_root=proc,
            fs_root=fs,
            uid=uid,
        )
    elif args.command == "authorize":
        result = authorize_containment(
            state,
            args.incident_id,
            args.proposal_id,
            confirm=args.confirm,
            ttl_seconds=args.ttl,
        )
    elif args.command == "execute":
        result = execute_authorized(
            state,
            args.authority_id,
            db_root=db,
            proc_root=proc,
            fs_root=fs,
            uid=uid,
        )
    elif args.command == "authorize-release":
        result = authorize_release(
            state,
            args.incident_id,
            args.receipt_id,
            confirm=args.confirm,
            ttl_seconds=args.ttl,
        )
    else:
        result = execute_release(
            state,
            args.authority_id,
            db_root=db,
            proc_root=proc,
            fs_root=fs,
            uid=uid,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
