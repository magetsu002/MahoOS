#!/usr/bin/env python3
"""User-authorized live recovery of the Maho runtime after exact containment."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from typing import Any, Mapping, Protocol

from guardian_causality import CausalEdge, CausalGraph, CausalNode, RelationStrength
from guardian_evidence import parse_timestamp, utc_stamp
from guardian_live_response import plan_incident
from guardian_security_recovery import SecurityRecoveryOutcome, plan_security_recovery
from maho_runtime_release import verify_release

SCHEMA_VERSION = 1
DEFAULT_AUTHORITY_SECONDS = 120
MANAGED_RUNTIME_UNITS = (
    "maho-observe.service",
    "maho-security.service",
    "maho-guardian.service",
    "maho-awww-daemon.service",
    "maho-wallpaper.service",
    "maho-shell.service",
    "maho-dock.service",
    "maho-notify.service",
    "maho-clipboard-history.service",
    "maho-adaptive.service",
)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read(path: Path) -> dict[str, Any] | None:
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
    return state_root / "guardian" / "live-recovery"


def _active_path(state_root: Path, incident_id: str) -> Path:
    return _root(state_root) / "active" / f"{incident_id}.json"


def _authority_path(state_root: Path, authority_id: str) -> Path:
    return _root(state_root) / "authorizations" / f"{authority_id}.json"


def _receipt_path(state_root: Path, receipt_id: str) -> Path:
    return _root(state_root) / "receipts" / f"{receipt_id}.json"


def _containment_path(state_root: Path, incident_id: str) -> Path:
    return state_root / "guardian" / "live-response" / "active" / f"{incident_id}.json"


def _source_incident(state_root: Path, incident_id: str) -> dict[str, Any] | None:
    return _read(state_root / "incidents" / "active" / f"{incident_id}.json")


def _history(state_root: Path, event: str, payload: Mapping[str, Any]) -> None:
    path = _root(state_root) / "history.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    record = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-recovery-history",
        "event": event,
        "at": utc_stamp(datetime.now(timezone.utc)),
        "payload": dict(payload),
    }
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, _canonical(record) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, 0o600)


def _claim_authority(state_root: Path, authority_id: str) -> bool:
    path = _root(state_root) / "authorizations" / "consumed" / f"{authority_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-recovery-authority-consumption",
        "authority_id": authority_id,
        "consumed_at": utc_stamp(datetime.now(timezone.utc)),
    }
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        os.write(fd, _canonical(payload) + b"\n")
        os.fsync(fd)
    finally:
        os.close(fd)
    return True


def _graph_from_payload(payload: Mapping[str, Any]) -> CausalGraph:
    nodes_raw = payload.get("nodes")
    edges_raw = payload.get("edges")
    if not isinstance(nodes_raw, list) or not isinstance(edges_raw, list):
        raise ValueError("causal graph payload is invalid")
    nodes = tuple(
        CausalNode(
            node_id=str(row["node_id"]),
            kind=str(row["kind"]),
            subject=str(row["subject"]),
            evidence_ids=tuple(str(item) for item in row.get("evidence_ids", [])),
            attributes=dict(row.get("attributes") or {}),
        )
        for row in nodes_raw
        if isinstance(row, Mapping)
    )
    edges = tuple(
        CausalEdge(
            source=str(row["source"]),
            target=str(row["target"]),
            relation=str(row["relation"]),
            strength=RelationStrength(str(row["strength"])),
            reason=str(row["reason"]),
            proof=str(row["proof"]),
            evidence_ids=tuple(str(item) for item in row.get("evidence_ids", [])),
            edge_id=str(row.get("edge_id") or ""),
        )
        for row in edges_raw
        if isinstance(row, Mapping)
    )
    graph = CausalGraph(nodes, edges)
    if graph.as_dict() != dict(payload):
        raise ValueError("causal graph canonicalization drifted")
    return graph


def _release_identified(result: Any) -> bool:
    return not bool(
        {"release_unavailable", "release_not_direct_child", "release_identity_invalid"}
        .intersection(set(result.reasons))
    )


def _runtime_evidence(
    runtime_root: Path,
    *,
    require_previous_verified: bool = True,
) -> dict[str, Any]:
    releases = runtime_root / "releases"
    current_link = runtime_root / "current"
    previous_link = runtime_root / "previous"
    if not current_link.is_symlink() or not previous_link.is_symlink():
        raise ValueError("current and previous Maho runtime pointers are required")
    try:
        current_path = current_link.resolve(strict=True)
        previous_path = previous_link.resolve(strict=True)
    except OSError as exc:
        raise ValueError("Maho runtime pointer target is unavailable") from exc
    current = verify_release(current_path, releases)
    previous = verify_release(previous_path, releases)
    if not _release_identified(current):
        raise ValueError("current Maho runtime identity cannot be bounded")
    if require_previous_verified and not previous.verified:
        raise ValueError("previous Maho runtime is not independently verified")
    if current_path == previous_path:
        raise ValueError("current and previous Maho runtimes are identical")
    return {
        "runtime_root": str(runtime_root.resolve(strict=True)),
        "releases_root": str(releases.resolve(strict=True)),
        "current_link": str(current_link),
        "previous_link": str(previous_link),
        "current": current.as_dict(),
        "previous": previous.as_dict(),
    }


def _proposal_binding(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "incident_id": record.get("incident_id"),
        "containment_proposal_id": record.get("containment_proposal_id"),
        "containment_receipt_id": record.get("containment_receipt_id"),
        "containment_receipt_digest": record.get("containment_receipt_digest"),
        "evidence_digest": record.get("evidence_digest"),
        "graph_digest": record.get("graph_digest"),
        "target_digest": record.get("target_digest"),
        "current_runtime_path": (record.get("runtime") or {}).get("current", {}).get("path"),
        "current_runtime_content_sha256": (record.get("runtime") or {}).get("current", {}).get("content_sha256"),
        "previous_runtime_path": (record.get("runtime") or {}).get("previous", {}).get("path"),
        "previous_runtime_content_sha256": (record.get("runtime") or {}).get("previous", {}).get("content_sha256"),
    }


def _runtime_integrity_binding(source: Mapping[str, Any], runtime: Mapping[str, Any]) -> dict[str, Any] | None:
    subject = source.get("subject") if isinstance(source.get("subject"), Mapping) else {}
    if subject.get("type") != "runtime" or subject.get("id") != "maho-runtime":
        return None
    current = runtime.get("current") if isinstance(runtime.get("current"), Mapping) else {}
    if current.get("verified") is True:
        return None
    current_path = str(current.get("path") or "")
    current_reasons = sorted(str(item) for item in current.get("reasons", []) if isinstance(item, str))
    rows = source.get("signals") if isinstance(source.get("signals"), list) else []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if row.get("kind") != "runtime-integrity-drift" or row.get("source") != "maho-runtime-verifier":
            continue
        details = row.get("details") if isinstance(row.get("details"), Mapping) else {}
        reasons = sorted(str(item) for item in details.get("reasons", []) if isinstance(item, str))
        if (
            details.get("verified") is False
            and str(details.get("path") or "") == current_path
            and reasons == current_reasons
        ):
            return {
                "kind": "immutable-runtime-integrity",
                "source_incident_digest": _digest(source),
                "current_runtime_path": current_path,
                "current_runtime_reasons": current_reasons,
            }
    return None


def plan_runtime_recovery(
    state_root: Path,
    incident_id: str,
    *,
    db_root: Path,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
) -> dict[str, Any]:
    existing_recovery = _read(_active_path(state_root, incident_id))
    if existing_recovery is not None and existing_recovery.get("state") in {
        "recovering", "recovered", "verification-failed",
    }:
        return {
            "state": "none",
            "incident_id": incident_id,
            "reason": f"recovery-{existing_recovery.get('state')}-requires-new-incident",
        }

    source = _source_incident(state_root, incident_id)
    assessment = _read(state_root / "guardian" / "active" / f"{incident_id}.json")
    if (
        source is None
        or source.get("status") not in {None, "active"}
        or assessment is None
        or assessment.get("status") != "active"
    ):
        return {"state": "none", "incident_id": incident_id, "reason": "active-security-incident-unavailable"}

    try:
        runtime = _runtime_evidence(runtime_root)
    except ValueError as exc:
        return {"state": "none", "incident_id": incident_id, "reason": str(exc)}

    subject = source.get("subject") if isinstance(source.get("subject"), Mapping) else {}
    trigger: dict[str, Any]
    graph: CausalGraph | None = None

    if subject.get("type") == "runtime" and subject.get("id") == "maho-runtime":
        binding = _runtime_integrity_binding(source, runtime)
        if binding is None:
            return {
                "state": "none",
                "incident_id": incident_id,
                "reason": "runtime-integrity-evidence-no-longer-matches-current-release",
            }
        trigger = {
            **binding,
            "guardian_assessment_digest": _digest(assessment),
            "containment_proposal_id": None,
            "containment_receipt_id": None,
            "containment_receipt_digest": None,
            "graph_digest": None,
            "target_digest": None,
        }
    else:
        containment = _read(_containment_path(state_root, incident_id))
        if containment is None or containment.get("state") != "contained":
            return {"state": "none", "incident_id": incident_id, "reason": "exact-containment-not-active"}
        fresh = plan_incident(
            state_root,
            incident_id,
            db_root=db_root,
            proc_root=proc_root,
            fs_root=fs_root,
            uid=os.getuid() if uid is None else uid,
        )
        if fresh.get("state") != "authorization-required":
            return {
                "state": "none",
                "incident_id": incident_id,
                "reason": "fresh-causal-containment-proof-unavailable",
            }
        for key in (
            "proposal_id", "evidence_digest", "graph_digest", "target_digest",
            "process_identity_digest",
        ):
            if containment.get(key) != fresh.get(key):
                return {
                    "state": "none",
                    "incident_id": incident_id,
                    "reason": f"containment-binding-drift:{key}",
                }
        graph_payload = fresh.get("causal_graph")
        if not isinstance(graph_payload, Mapping):
            return {"state": "none", "incident_id": incident_id, "reason": "causal-graph-unavailable"}
        try:
            graph = _graph_from_payload(graph_payload)
        except ValueError as exc:
            return {"state": "none", "incident_id": incident_id, "reason": str(exc)}
        if _digest(graph.as_dict()) != fresh.get("graph_digest"):
            return {"state": "none", "incident_id": incident_id, "reason": "causal graph digest mismatch"}
        trigger = {
            "kind": "contained-process-target",
            "source_incident_digest": _digest(source),
            "guardian_assessment_digest": _digest(assessment),
            "containment_proposal_id": containment.get("proposal_id"),
            "containment_receipt_id": containment.get("receipt_id"),
            "containment_receipt_digest": containment.get("receipt_digest"),
            "graph_digest": fresh.get("graph_digest"),
            "target_digest": fresh.get("target_digest"),
        }

    handoff = plan_security_recovery(
        source,
        causal_graph=graph,
        previous_runtime_available=True,
        runtime_transaction_authorized=False,
    )
    if handoff.outcome is not SecurityRecoveryOutcome.AUTHORIZATION_REQUIRED:
        return {
            "state": "none",
            "incident_id": incident_id,
            "reason": "security-recovery-not-user-authorizable",
            "handoff": handoff.as_dict(),
        }
    if handoff.provider != "maho-runtime" or handoff.action != "rollback-previous":
        return {"state": "none", "incident_id": incident_id, "reason": "runtime-recovery-provider-mismatch"}

    material = {
        "incident_id": incident_id,
        "trigger": trigger,
        "runtime": runtime,
        "handoff": handoff.as_dict(),
    }
    proposal_digest = _digest(material)
    proposal_id = "recovery-" + proposal_digest[:24]
    proposal = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery",
        "state": "authorization-required",
        "incident_id": incident_id,
        "proposal_id": proposal_id,
        "proposal_digest": proposal_digest,
        "captured_at": utc_stamp(datetime.now(timezone.utc)),
        "trigger": trigger,
        "containment_proposal_id": trigger.get("containment_proposal_id"),
        "containment_receipt_id": trigger.get("containment_receipt_id"),
        "containment_receipt_digest": trigger.get("containment_receipt_digest"),
        "evidence_digest": _digest(trigger),
        "graph_digest": trigger.get("graph_digest"),
        "target_digest": trigger.get("target_digest"),
        "runtime": runtime,
        "handoff": handoff.as_dict(),
        "authorization_required": True,
        "automatic_authority": False,
        "postcondition": "verified-previous-is-current-and-managed-wiring-and-active-maho-services-verified",
    }
    existing = _read(_active_path(state_root, incident_id))
    if existing is None or existing.get("proposal_id") != proposal_id:
        _atomic_private(_active_path(state_root, incident_id), proposal)
        _history(state_root, "authorization-required", proposal)
    return proposal

def recovery_status(state_root: Path) -> dict[str, Any]:
    active = _root(state_root) / "active"
    rows: list[dict[str, Any]] = []
    if active.is_dir():
        for path in sorted(active.glob("inc-*.json")):
            row = _read(path)
            if row is None:
                continue
            rows.append({
                "incident_id": row.get("incident_id"),
                "proposal_id": row.get("proposal_id"),
                "state": row.get("state"),
                "receipt_id": row.get("receipt_id"),
                "reason": row.get("reason"),
            })
    states = {str(row.get("state")) for row in rows}
    state = "verification-failed" if "verification-failed" in states else (
        "recovering" if "recovering" in states else
        "authorization-required" if "authorization-required" in states else
        "recovered" if "recovered" in states else "none"
    )
    return {
        "state": state,
        "active": rows,
        "automatic_authority": False,
        "history_retained": True,
    }


def authorize_runtime_recovery(
    state_root: Path,
    incident_id: str,
    proposal_id: str,
    *,
    confirm: str,
    ttl_seconds: int = DEFAULT_AUTHORITY_SECONDS,
) -> dict[str, Any]:
    proposal = _read(_active_path(state_root, incident_id))
    if proposal is None or proposal.get("state") != "authorization-required":
        return {"result": "refused", "reason": "recovery-proposal-not-active"}
    if proposal.get("proposal_id") != proposal_id:
        return {"result": "refused", "reason": "recovery-proposal-id-mismatch"}
    if confirm != f"AUTHORIZE-RUNTIME-RECOVERY:{proposal_id}":
        return {"result": "denied", "reason": "explicit-recovery-authorization-token-mismatch"}
    now = datetime.now(timezone.utc)
    ttl = min(max(int(ttl_seconds), 1), 300)
    authority_id = "recovery-auth-" + secrets.token_hex(12)
    authority = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery-authorization",
        "authority_id": authority_id,
        "action": "rollback-previous",
        "user_authorized": True,
        "issued_at": utc_stamp(now),
        "expires_at": utc_stamp(now + timedelta(seconds=ttl)),
        "proposal_id": proposal_id,
        "binding": _proposal_binding(proposal),
        "proposal_digest": proposal.get("proposal_digest"),
    }
    _atomic_private(_authority_path(state_root, authority_id), authority)
    _history(state_root, "recovery-authorized", authority)
    return authority


def _authority_error(authority: Mapping[str, Any]) -> str | None:
    if authority.get("user_authorized") is not True or authority.get("action") != "rollback-previous":
        return "recovery-authorization-action-mismatch"
    try:
        issued = parse_timestamp(str(authority.get("issued_at")))
        expires = parse_timestamp(str(authority.get("expires_at")))
    except ValueError:
        return "recovery-authorization-window-invalid"
    now = datetime.now(timezone.utc)
    if issued is None or expires is None or now < issued or now > expires:
        return "recovery-authorization-expired"
    return None


def _verify_runtime_rotation(runtime_root: Path, proposal: Mapping[str, Any]) -> dict[str, Any]:
    runtime = proposal.get("runtime")
    if not isinstance(runtime, Mapping):
        return {"ok": False, "reason": "runtime-evidence-missing"}
    expected_previous = str((runtime.get("previous") or {}).get("path") or "")
    expected_current = str((runtime.get("current") or {}).get("path") or "")
    try:
        observed = _runtime_evidence(runtime_root, require_previous_verified=False)
    except ValueError as exc:
        return {"ok": False, "reason": f"runtime-postcondition:{exc}"}
    current_path = str((observed.get("current") or {}).get("path") or "")
    previous_path = str((observed.get("previous") or {}).get("path") or "")
    return {
        "ok": (
            current_path == expected_previous
            and previous_path == expected_current
            and (observed.get("current") or {}).get("verified") is True
        ),
        "current_is_authorized_previous": current_path == expected_previous,
        "previous_is_authorized_old_current": previous_path == expected_current,
        "current_release_verified": (observed.get("current") or {}).get("verified") is True,
        "observed_runtime": observed,
    }


class RuntimeRollbackDriver(Protocol):
    def execute(self, proposal: Mapping[str, Any]) -> Mapping[str, Any]: ...


class MahoSetupRollbackDriver:
    def __init__(self, runtime_root: Path):
        self.runtime_root = runtime_root

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            text=True,
            capture_output=True,
            check=False,
            env=os.environ.copy(),
        )

    def _active_units(self) -> tuple[str, ...]:
        active: list[str] = []
        for unit in MANAGED_RUNTIME_UNITS:
            result = self._run(["/usr/bin/systemctl", "--user", "is-active", "--quiet", unit])
            if result.returncode == 0:
                active.append(unit)
        return tuple(active)

    def execute(self, proposal: Mapping[str, Any]) -> Mapping[str, Any]:
        runtime = proposal.get("runtime")
        if not isinstance(runtime, Mapping):
            return {"ok": False, "reason": "runtime-evidence-missing"}
        expected_previous = str((runtime.get("previous") or {}).get("path") or "")
        expected_current = str((runtime.get("current") or {}).get("path") or "")
        try:
            before = _runtime_evidence(self.runtime_root)
        except ValueError as exc:
            return {"ok": False, "reason": f"runtime-precondition:{exc}"}
        if (
            str(before["current"]["path"]) != expected_current
            or str(before["previous"]["path"]) != expected_previous
        ):
            return {"ok": False, "reason": "runtime-pointer-binding-drift"}

        previous = Path(expected_previous)
        executor = previous / "bin/maho-setup"
        if not executor.is_file():
            return {"ok": False, "reason": "verified-previous-runtime-lacks-maho-setup"}
        active_before = self._active_units()
        rollback = self._run(["/bin/bash", str(executor), "rollback"])
        if rollback.returncode != 0:
            return {
                "ok": False,
                "reason": "maho-setup-rollback-failed",
                "exit_code": rollback.returncode,
                "stdout_tail": rollback.stdout[-3000:],
                "stderr_tail": rollback.stderr[-3000:],
            }

        reload_result = self._run(["/usr/bin/systemctl", "--user", "daemon-reload"])
        restart_results: dict[str, bool] = {}
        for unit in active_before:
            restarted = self._run(["/usr/bin/systemctl", "--user", "restart", unit])
            restart_results[unit] = restarted.returncode == 0
        status_result = self._run(["/bin/bash", str(executor), "status"])
        try:
            after = _runtime_evidence(self.runtime_root, require_previous_verified=False)
        except ValueError as exc:
            return {
                "ok": False,
                "reason": f"runtime-postcondition:{exc}",
                "runtime_switched": True,
                "daemon_reload_verified": reload_result.returncode == 0,
                "service_restarts": restart_results,
            }
        current_is_previous = str(after["current"]["path"]) == expected_previous
        previous_is_old_current = str(after["previous"]["path"]) == expected_current
        services_ok = all(restart_results.values())
        verified = bool(
            current_is_previous
            and previous_is_old_current
            and after["current"]["verified"] is True
            and reload_result.returncode == 0
            and status_result.returncode == 0
            and services_ok
        )
        return {
            "ok": verified,
            "runtime_switched": current_is_previous,
            "previous_pointer_rotated": previous_is_old_current,
            "observed_runtime": after,
            "daemon_reload_verified": reload_result.returncode == 0,
            "managed_wiring_verified": status_result.returncode == 0,
            "active_units_before": list(active_before),
            "service_restarts": restart_results,
            "services_verified": services_ok,
            "rollback_stdout_tail": rollback.stdout[-3000:],
            "rollback_stderr_tail": rollback.stderr[-3000:],
            "reason": None if verified else "runtime-recovery-postcondition-failed",
        }


def execute_runtime_recovery(
    state_root: Path,
    authority_id: str,
    *,
    db_root: Path,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
    driver: RuntimeRollbackDriver | None = None,
) -> dict[str, Any]:
    authority = _read(_authority_path(state_root, authority_id))
    if authority is None:
        return {"result": "refused", "reason": "recovery-authorization-unavailable"}
    error = _authority_error(authority)
    if error is not None:
        return {"result": "refused", "reason": error}
    binding = authority.get("binding")
    if not isinstance(binding, Mapping):
        return {"result": "refused", "reason": "recovery-authorization-binding-invalid"}
    incident_id = str(binding.get("incident_id") or "")
    proposal = plan_runtime_recovery(
        state_root,
        incident_id,
        db_root=db_root,
        runtime_root=runtime_root,
        proc_root=proc_root,
        fs_root=fs_root,
        uid=uid,
    )
    if proposal.get("state") != "authorization-required":
        return {"result": "refused", "reason": "recovery-proposal-no-longer-current"}
    if (
        proposal.get("proposal_id") != authority.get("proposal_id")
        or _proposal_binding(proposal) != dict(binding)
        or proposal.get("proposal_digest") != authority.get("proposal_digest")
    ):
        return {"result": "refused", "reason": "recovery-authorization-binding-changed"}
    if not _claim_authority(state_root, authority_id):
        return {"result": "refused", "reason": "recovery-authorization-already-consumed"}

    recovering = {
        **proposal,
        "state": "recovering",
        "authority_id": authority_id,
    }
    _atomic_private(_active_path(state_root, incident_id), recovering)
    _history(state_root, "recovering", recovering)
    executor = driver or MahoSetupRollbackDriver(runtime_root)
    evidence = dict(executor.execute(proposal))
    rotation = _verify_runtime_rotation(runtime_root, proposal)
    evidence["coordinator_runtime_postcondition"] = rotation
    evidence["ok"] = bool(evidence.get("ok") is True and rotation.get("ok") is True)
    if evidence["ok"] is not True and not evidence.get("reason"):
        evidence["reason"] = "runtime-recovery-postcondition-failed"
    receipt_id = "recovery-receipt-" + _digest({
        "authority_id": authority_id,
        "proposal_id": proposal["proposal_id"],
        "evidence": evidence,
    })[:24]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery-receipt",
        "receipt_id": receipt_id,
        "incident_id": incident_id,
        "proposal_id": proposal["proposal_id"],
        "authority_id": authority_id,
        "binding": _proposal_binding(proposal),
        "evidence": evidence,
        "verified": evidence.get("ok") is True,
        "completed_at": utc_stamp(datetime.now(timezone.utc)),
    }
    receipt["receipt_digest"] = _digest(receipt)
    _atomic_private(_receipt_path(state_root, receipt_id), receipt)

    if evidence.get("ok") is True:
        final = {
            **proposal,
            "state": "recovered",
            "authority_id": authority_id,
            "receipt_id": receipt_id,
            "receipt_digest": receipt["receipt_digest"],
            "verified": True,
        }
        _atomic_private(_active_path(state_root, incident_id), final)
        _history(state_root, "recovered", final)
        return {
            "result": "recovered",
            "verified": True,
            "incident_id": incident_id,
            "receipt_id": receipt_id,
        }

    failed = {
        **proposal,
        "state": "verification-failed",
        "authority_id": authority_id,
        "receipt_id": receipt_id,
        "receipt_digest": receipt["receipt_digest"],
        "verified": False,
        "reason": evidence.get("reason") or "runtime-recovery-postcondition-failed",
    }
    _atomic_private(_active_path(state_root, incident_id), failed)
    _history(state_root, "recovery-verification-failed", failed)
    return {
        "result": "verification-failed",
        "verified": False,
        "incident_id": incident_id,
        "receipt_id": receipt_id,
        "detail": evidence,
    }


def reconcile_runtime_recovery(
    state_root: Path,
    *,
    db_root: Path,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
) -> dict[str, Any]:
    containment_dir = state_root / "guardian" / "live-response" / "active"
    incident_ids: set[str] = set()
    if containment_dir.is_dir():
        for path in sorted(containment_dir.glob("inc-*.json")):
            row = _read(path)
            if row is not None and row.get("state") == "contained":
                incident_ids.add(path.stem)
    security_dir = state_root / "incidents" / "active"
    if security_dir.is_dir():
        for path in sorted(security_dir.glob("inc-*.json")):
            row = _read(path)
            subject = row.get("subject") if isinstance(row, Mapping) and isinstance(row.get("subject"), Mapping) else {}
            if (
                isinstance(row, Mapping)
                and row.get("status") in {None, "active"}
                and subject.get("type") == "runtime"
                and subject.get("id") == "maho-runtime"
            ):
                incident_ids.add(path.stem)
    results: list[dict[str, Any]] = []
    for incident_id in sorted(incident_ids):
        current = _read(_active_path(state_root, incident_id))
        if current is not None and current.get("state") in {
            "recovering", "recovered", "verification-failed",
        }:
            results.append(current)
            continue
        proposal = plan_runtime_recovery(
            state_root,
            incident_id,
            db_root=db_root,
            runtime_root=runtime_root,
            proc_root=proc_root,
            fs_root=fs_root,
            uid=uid,
        )
        if proposal.get("state") == "authorization-required":
            results.append(proposal)
    return {
        "state": recovery_status(state_root)["state"],
        "active": results,
        "automatic_authority": False,
    }


def recovery_loop(
    state_root: Path,
    *,
    interval: float = 5.0,
    db_root: Path | None = None,
    runtime_root: Path | None = None,
    proc_root: Path | None = None,
    fs_root: Path | None = None,
) -> None:
    delay = max(1.0, float(interval))
    db = db_root or Path(os.environ.get("MAHO_PACMAN_DB_ROOT", "/var/lib/pacman/local"))
    runtime = runtime_root or Path(
        os.environ.get("MAHO_RUNTIME_ROOT")
        or str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "maho/runtime")
    )
    proc = proc_root or Path(os.environ.get("MAHO_PROC_ROOT", "/proc"))
    fs = fs_root or Path(os.environ.get("MAHO_FS_ROOT", "/"))
    while True:
        try:
            reconcile_runtime_recovery(
                state_root,
                db_root=db,
                runtime_root=runtime,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="guardian-live-recovery")
    parser.add_argument(
        "--state-root",
        default=str(Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "maho/security"),
    )
    parser.add_argument("--db-root", default=os.environ.get("MAHO_PACMAN_DB_ROOT", "/var/lib/pacman/local"))
    parser.add_argument("--proc-root", default=os.environ.get("MAHO_PROC_ROOT", "/proc"))
    parser.add_argument("--fs-root", default=os.environ.get("MAHO_FS_ROOT", "/"))
    parser.add_argument(
        "--runtime-root",
        default=os.environ.get("MAHO_RUNTIME_ROOT") or str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "maho/runtime"),
    )
    parser.add_argument("--uid", type=int)
    sub = parser.add_subparsers(dest="command", required=True)
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
    args = parser.parse_args(argv)

    state = Path(args.state_root)
    db = Path(args.db_root)
    proc = Path(args.proc_root)
    fs = Path(args.fs_root)
    runtime = Path(args.runtime_root)
    uid = args.uid if args.uid is not None else os.getuid()
    if args.command == "status":
        result = recovery_status(state)
    elif args.command == "plan":
        result = plan_runtime_recovery(
            state, args.incident_id, db_root=db, runtime_root=runtime,
            proc_root=proc, fs_root=fs, uid=uid,
        )
    elif args.command == "authorize":
        result = authorize_runtime_recovery(
            state, args.incident_id, args.proposal_id,
            confirm=args.confirm, ttl_seconds=args.ttl,
        )
    else:
        result = execute_runtime_recovery(
            state, args.authority_id, db_root=db, runtime_root=runtime,
            proc_root=proc, fs_root=fs, uid=uid,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
