#!/usr/bin/env python3
"""User-authorized live recovery of the Maho runtime after exact containment."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from typing import Any, Mapping, Protocol

from guardian_causality import CausalEdge, CausalGraph, CausalNode, RelationStrength
from guardian_evidence import ProviderHealth, parse_timestamp, utc_stamp
from guardian_provider_state import load_heartbeat
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

AUTO_PROVIDER_MAX_AGE = {
    "security.packages": 900.0,
    "security.persistence": 900.0,
    "security.runtime": 900.0,
    "security.privilege": 900.0,
    "security.network": 900.0,
    "security.integrity": 2400.0,
    "guardian.watch": 90.0,
    "guardian.service-events": 90.0,
}
AUTO_POST_RECOVERY_OBSERVERS = ("guardian.watch", "security.runtime")
AUTO_RECOVERY_PROPOSAL_MAX_AGE_SECONDS = 120.0
AUTO_VERIFICATION_TIMEOUT_SECONDS = 120.0


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
    current_observed_identity = str(current.get("observed_content_sha256") or "")
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
            and str(details.get("observed_content_sha256") or "") == current_observed_identity
            and reasons == current_reasons
        ):
            return {
                "kind": "immutable-runtime-integrity",
                "source_incident_digest": _digest(source),
                "current_runtime_path": current_path,
                "current_runtime_observed_content_sha256": current_observed_identity,
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
        "recovering", "verifying", "recovered", "verification-failed", "evidence-insufficient",
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
                "automatic_authority": row.get("automatic_authority") is True,
                "exposure": row.get("exposure"),
            })
    states = {str(row.get("state")) for row in rows}
    state = "verification-failed" if "verification-failed" in states else (
        "evidence-insufficient" if "evidence-insufficient" in states else
        "recovering" if "recovering" in states else
        "verifying" if "verifying" in states else
        "authorization-required" if "authorization-required" in states else
        "recovered" if "recovered" in states else "none"
    )
    return {
        "state": state,
        "active": rows,
        "automatic_authority": any(row.get("automatic_authority") is True for row in rows),
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



def _automatic_provider_snapshot(
    state_root: Path,
    *,
    now: datetime | None = None,
    expected_boot_id: str | None = None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows: dict[str, Any] = {}
    reasons: list[str] = []
    for provider_id, max_age in AUTO_PROVIDER_MAX_AGE.items():
        try:
            heartbeat = load_heartbeat(state_root, provider_id)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            heartbeat = None
            reasons.append(f"provider-malformed:{provider_id}")
        if heartbeat is None:
            rows[provider_id] = {
                "health": ProviderHealth.UNKNOWN.value,
                "last_success_at": None,
                "age_seconds": None,
                "max_age_seconds": max_age,
                "current": False,
            }
            if f"provider-malformed:{provider_id}" not in reasons:
                reasons.append(f"provider-missing:{provider_id}")
            continue
        observed = parse_timestamp(heartbeat.last_success_at) if heartbeat.last_success_at else None
        age = (current - observed).total_seconds() if observed is not None else None
        boot_matches = bool(
            expected_boot_id
            and heartbeat.boot_id
            and heartbeat.boot_id.replace("-", "").lower()
                == expected_boot_id.replace("-", "").lower()
        )
        fresh = bool(
            observed is not None
            and age is not None
            and -5.0 <= age <= max_age
            and heartbeat.health is ProviderHealth.HEALTHY
            and boot_matches
        )
        rows[provider_id] = {
            "health": heartbeat.health.value,
            "last_success_at": heartbeat.last_success_at,
            "last_attempt_at": heartbeat.last_attempt_at,
            "age_seconds": age,
            "max_age_seconds": max_age,
            "current": fresh,
            "sequence": heartbeat.sequence,
            "source": heartbeat.source,
            "authority_boundary": heartbeat.authority_boundary,
            "boot_id": heartbeat.boot_id,
            "expected_boot_id": expected_boot_id,
            "boot_matches": boot_matches,
            "errors": list(heartbeat.errors),
        }
        if not expected_boot_id:
            reasons.append("current-boot-identity-unavailable")
        elif not heartbeat.boot_id:
            reasons.append(f"provider-boot-unknown:{provider_id}")
        elif not boot_matches:
            reasons.append(f"provider-boot-mismatch:{provider_id}")
        if heartbeat.health is not ProviderHealth.HEALTHY:
            reasons.append(f"provider-unhealthy:{provider_id}:{heartbeat.health.value}")
        elif observed is None:
            reasons.append(f"provider-no-success:{provider_id}")
        elif age is not None and age < -5.0:
            reasons.append(f"provider-clock-ahead:{provider_id}")
        elif age is not None and age > max_age:
            reasons.append(f"provider-stale:{provider_id}")
    return rows, tuple(dict.fromkeys(reasons))


def automatic_recovery_policy(
    state_root: Path,
    proposal: Mapping[str, Any],
    *,
    now: datetime | None = None,
    proc_root: Path = Path("/proc"),
) -> dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reasons: list[str] = []
    source = _source_incident(state_root, str(proposal.get("incident_id") or ""))
    assessment = _read(
        state_root / "guardian" / "active" / f"{proposal.get('incident_id')}.json"
    )
    trigger = proposal.get("trigger") if isinstance(proposal.get("trigger"), Mapping) else {}
    runtime = proposal.get("runtime") if isinstance(proposal.get("runtime"), Mapping) else {}
    current_runtime = runtime.get("current") if isinstance(runtime.get("current"), Mapping) else {}
    previous_runtime = runtime.get("previous") if isinstance(runtime.get("previous"), Mapping) else {}
    handoff = proposal.get("handoff") if isinstance(proposal.get("handoff"), Mapping) else {}

    if proposal.get("state") != "authorization-required":
        reasons.append("proposal-not-current")
    if trigger.get("kind") != "immutable-runtime-integrity":
        reasons.append("incident-class-not-automatic")
    if proposal.get("containment_proposal_id") is not None or proposal.get("containment_receipt_id") is not None:
        reasons.append("automatic-scope-requires-no-process-containment")
    if source is None:
        reasons.append("source-incident-unavailable")
    else:
        subject = source.get("subject") if isinstance(source.get("subject"), Mapping) else {}
        if subject != {"type": "runtime", "id": "maho-runtime"}:
            reasons.append("source-subject-not-exact-maho-runtime")
        if source.get("confidence") != "confirmed":
            reasons.append("source-incident-not-confirmed")
        if _digest(source) != trigger.get("source_incident_digest"):
            reasons.append("source-incident-binding-drift")
    if assessment is None or assessment.get("status") != "active":
        reasons.append("guardian-assessment-unavailable")
    elif _digest(assessment) != trigger.get("guardian_assessment_digest"):
        reasons.append("guardian-assessment-binding-drift")

    if current_runtime.get("verified") is not False:
        reasons.append("current-runtime-not-proven-bad")
    if previous_runtime.get("verified") is not True:
        reasons.append("known-good-runtime-unavailable")
    if not current_runtime.get("path") or not previous_runtime.get("path"):
        reasons.append("runtime-identity-incomplete")
    if current_runtime.get("path") == previous_runtime.get("path"):
        reasons.append("runtime-pair-not-distinct")
    if handoff.get("provider") != "maho-runtime" or handoff.get("action") != "rollback-previous":
        reasons.append("recovery-provider-not-exact-runtime-rollback")

    captured = None
    try:
        captured = parse_timestamp(str(proposal.get("captured_at")))
    except ValueError:
        reasons.append("proposal-time-invalid")
    if captured is None:
        reasons.append("proposal-time-missing")
    else:
        proposal_age = (current - captured).total_seconds()
        if proposal_age < -5.0 or proposal_age > AUTO_RECOVERY_PROPOSAL_MAX_AGE_SECONDS:
            reasons.append("recovery-authority-stale")

    if not state_root.is_dir() or not os.access(state_root, os.R_OK | os.W_OK):
        reasons.append("guardian-durable-state-unavailable")

    try:
        expected_boot_id = (proc_root / "sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() or None
    except OSError:
        expected_boot_id = None
    providers, provider_reasons = _automatic_provider_snapshot(
        state_root,
        now=current,
        expected_boot_id=expected_boot_id,
    )
    reasons.extend(provider_reasons)
    allowed = not reasons
    return {
        "allowed": allowed,
        "scope": "runtime-only",
        "action": "rollback-previous",
        "incident_class": "exact-maho-runtime-integrity",
        "guardian_action_health": "HEALTHY" if allowed else "DEGRADED",
        "global_trust_promoted": False,
        "reasons": list(dict.fromkeys(reasons)),
        "providers": providers,
        "evaluated_at": utc_stamp(current),
        "exposure": {
            "state": "unknown",
            "reason": "runtime recovery restores system state but does not prove whether damaged code executed before recovery",
        },
    }


def _automatic_evidence_path(state_root: Path, incident_id: str, proposal_id: str) -> Path:
    safe = f"{incident_id}--{proposal_id}".replace("/", "_")
    return _root(state_root) / "evidence" / f"{safe}.json"


def _preserve_automatic_evidence(
    state_root: Path,
    proposal: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    incident_id = str(proposal.get("incident_id") or "")
    proposal_id = str(proposal.get("proposal_id") or "")
    path = _automatic_evidence_path(state_root, incident_id, proposal_id)
    existing = _read(path)
    if existing is not None:
        return existing
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery-evidence",
        "incident_id": incident_id,
        "proposal_id": proposal_id,
        "preserved_at": utc_stamp(datetime.now(timezone.utc)),
        "source_incident": _source_incident(state_root, incident_id),
        "guardian_assessment": _read(state_root / "guardian" / "active" / f"{incident_id}.json"),
        "proposal": dict(proposal),
        "automatic_decision": dict(decision),
    }
    payload["evidence_snapshot_digest"] = _digest(payload)
    _atomic_private(path, payload)
    _history(
        state_root,
        "automatic-evidence-preserved",
        {
            "incident_id": incident_id,
            "proposal_id": proposal_id,
            "evidence_snapshot_digest": payload["evidence_snapshot_digest"],
            "path": str(path),
        },
    )
    return payload


def _automatic_operation_id(
    proposal: Mapping[str, Any],
    evidence_snapshot: Mapping[str, Any],
) -> str:
    return "auto-recovery-" + _digest(
        {
            "proposal_id": proposal.get("proposal_id"),
            "proposal_digest": proposal.get("proposal_digest"),
            "evidence_snapshot_digest": evidence_snapshot.get("evidence_snapshot_digest"),
        }
    )[:24]


def _automatic_operation_path(state_root: Path, operation_id: str) -> Path:
    return _root(state_root) / "operations" / f"{operation_id}.json"


def _claim_automatic_operation(
    state_root: Path,
    operation_id: str,
    *,
    incident_id: str,
    proposal_id: str,
    evidence_snapshot_digest: str,
) -> tuple[bool, dict[str, Any] | None]:
    path = _automatic_operation_path(state_root, operation_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery-operation",
        "operation_id": operation_id,
        "incident_id": incident_id,
        "proposal_id": proposal_id,
        "evidence_snapshot_digest": evidence_snapshot_digest,
        "claimed_at": utc_stamp(datetime.now(timezone.utc)),
    }
    data = json.dumps(payload, indent=2, sort_keys=True).encode() + b"\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False, _read(path)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    return True, payload


def _try_lock_automatic_operation(state_root: Path, operation_id: str):
    """Own one runtime mutation without delaying a concurrent reconciler."""

    stream = _automatic_operation_path(state_root, operation_id).open("rb")
    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    return stream


def _automatic_operation_in_progress(active: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "result": "recovering",
        "verified": False,
        "incident_id": active.get("incident_id"),
        "operation_id": active.get("operation_id"),
        "in_progress": True,
    }


def _notification_marker(state_root: Path, incident_id: str, phase: str) -> Path:
    return _root(state_root) / "notifications" / f"{incident_id}--{phase}.json"


def _notify_once(
    state_root: Path,
    incident_id: str,
    phase: str,
    *,
    title: str,
    body: str,
) -> bool:
    marker = _notification_marker(state_root, incident_id, phase)
    if marker.exists():
        return False
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery-notification",
        "incident_id": incident_id,
        "phase": phase,
        "title": title,
        "body": body,
        "recorded_at": utc_stamp(datetime.now(timezone.utc)),
    }
    _atomic_private(marker, payload)
    _history(state_root, "notification", payload)

    state_home = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    live_root = state_home / "maho/security"
    if state_root.resolve() == live_root.resolve():
        notifier = Path("/usr/bin/notify-send")
        if notifier.is_file():
            subprocess.run(
                [str(notifier), title, body],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    return True


def _recovery_receipt_valid(state_root: Path, receipt_id: str) -> dict[str, Any] | None:
    row = _read(_receipt_path(state_root, receipt_id))
    if row is None:
        return None
    digest = row.get("receipt_digest")
    material = {key: value for key, value in row.items() if key != "receipt_digest"}
    if not isinstance(digest, str) or digest != _digest(material):
        return None
    return row


def _write_automatic_receipt(
    state_root: Path,
    active: Mapping[str, Any],
    *,
    operation_id: str,
    mutation_evidence: Mapping[str, Any],
    verified: bool,
    verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    receipt_id = str(active.get("receipt_id") or "")
    if not receipt_id:
        receipt_id = "recovery-receipt-" + _digest(
            {
                "authority_id": operation_id,
                "proposal_id": active.get("proposal_id"),
            }
        )[:24]
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "kind": "guardian-live-runtime-recovery-receipt",
        "receipt_id": receipt_id,
        "incident_id": active.get("incident_id"),
        "proposal_id": active.get("proposal_id"),
        "authority_id": operation_id,
        "automatic_authority": True,
        "binding": _proposal_binding(active),
        "evidence_snapshot_digest": active.get("evidence_snapshot_digest"),
        "evidence": dict(mutation_evidence),
        "verified": verified,
        "verification": dict(verification or {}),
        "completed_at": utc_stamp(datetime.now(timezone.utc)) if verified else None,
    }
    receipt["receipt_digest"] = _digest(receipt)
    _atomic_private(_receipt_path(state_root, receipt_id), receipt)
    return receipt


def _automatic_failure(
    state_root: Path,
    active: Mapping[str, Any],
    *,
    reason: str,
    verification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    incident_id = str(active.get("incident_id") or "")
    failed = {
        **dict(active),
        "state": "verification-failed",
        "verified": False,
        "reason": reason,
        "verification": dict(verification or {}),
        "exposure": active.get("exposure") or {
            "state": "unknown",
            "reason": "recovery failure cannot establish whether damaged code executed",
        },
    }
    _atomic_private(_active_path(state_root, incident_id), failed)
    _history(state_root, "recovery-verification-failed", failed)
    _notify_once(
        state_root,
        incident_id,
        "failed",
        title="Maho Guardian",
        body="Automatic recovery could not be verified. Review required.",
    )
    return {
        "result": "verification-failed",
        "verified": False,
        "incident_id": incident_id,
        "receipt_id": failed.get("receipt_id"),
        "reason": reason,
    }


def _automatic_evidence_insufficient(
    state_root: Path,
    active: Mapping[str, Any],
    *,
    decision: Mapping[str, Any],
) -> dict[str, Any]:
    incident_id = str(active.get("incident_id") or "")
    blocked = {
        **dict(active),
        "state": "evidence-insufficient",
        "automatic_authority": False,
        "verified": False,
        "reason": "automatic-resume-authority-not-current",
        "automatic_decision": dict(decision),
    }
    _atomic_private(_active_path(state_root, incident_id), blocked)
    _history(state_root, "automatic-evidence-insufficient", blocked)
    _notify_once(
        state_root,
        incident_id,
        "failed",
        title="Maho Guardian",
        body="Automatic recovery could not continue safely. Review required.",
    )
    return {
        "result": "evidence-insufficient",
        "verified": False,
        "incident_id": incident_id,
        "reason": blocked["reason"],
        "automatic_decision": dict(decision),
    }


def _runtime_pair_position(
    runtime_root: Path,
    proposal: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    runtime = proposal.get("runtime") if isinstance(proposal.get("runtime"), Mapping) else {}
    expected_current = str((runtime.get("current") or {}).get("path") or "")
    expected_previous = str((runtime.get("previous") or {}).get("path") or "")
    try:
        observed = _runtime_evidence(runtime_root, require_previous_verified=False)
    except ValueError as exc:
        return "ambiguous", {"ok": False, "reason": f"runtime-postcondition:{exc}"}
    current_path = str((observed.get("current") or {}).get("path") or "")
    previous_path = str((observed.get("previous") or {}).get("path") or "")
    if current_path == expected_current and previous_path == expected_previous:
        return "before", {"ok": True, "observed_runtime": observed}
    if (
        current_path == expected_previous
        and previous_path == expected_current
        and (observed.get("current") or {}).get("verified") is True
    ):
        return "after", {"ok": True, "observed_runtime": observed}
    return "ambiguous", {
        "ok": False,
        "reason": "runtime-pointer-state-ambiguous",
        "observed_runtime": observed,
    }


def _resume_automatic_runtime_recovery_locked(
    state_root: Path,
    incident_id: str,
    *,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    driver: RuntimeRollbackDriver | None = None,
) -> dict[str, Any]:
    active = _read(_active_path(state_root, incident_id))
    if active is None or active.get("state") != "recovering" or active.get("automatic_authority") is not True:
        return {"result": "refused", "reason": "automatic-recovery-not-resumable"}
    operation_id = str(active.get("operation_id") or "")
    claim = _read(_automatic_operation_path(state_root, operation_id)) if operation_id else None
    if (
        claim is None
        or claim.get("incident_id") != incident_id
        or claim.get("proposal_id") != active.get("proposal_id")
        or claim.get("evidence_snapshot_digest") != active.get("evidence_snapshot_digest")
    ):
        return _automatic_failure(
            state_root,
            active,
            reason="automatic-operation-claim-invalid",
        )

    position, observed = _runtime_pair_position(runtime_root, active)
    if position == "ambiguous":
        return _automatic_failure(
            state_root,
            active,
            reason=str(observed.get("reason") or "runtime-pointer-state-ambiguous"),
            verification={"runtime": observed},
        )

    if position == "after":
        mutation_evidence = {
            "ok": True,
            "resumed_after_interruption": True,
            "coordinator_runtime_postcondition": observed,
            "services_verified": None,
            "reason": None,
        }
    else:
        resume_proposal = {**active, "state": "authorization-required"}
        resume_decision = automatic_recovery_policy(
            state_root,
            resume_proposal,
            proc_root=proc_root,
        )
        if resume_decision.get("allowed") is not True:
            return _automatic_evidence_insufficient(
                state_root,
                active,
                decision=resume_decision,
            )
        executor = driver or MahoSetupRollbackDriver(runtime_root)
        started = time.monotonic()
        mutation_evidence = dict(executor.execute(active))
        mutation_evidence["duration_ms"] = round((time.monotonic() - started) * 1000.0, 3)
        rotation = _verify_runtime_rotation(runtime_root, active)
        mutation_evidence["coordinator_runtime_postcondition"] = rotation
        mutation_evidence["ok"] = bool(
            mutation_evidence.get("ok") is True and rotation.get("ok") is True
        )
        if mutation_evidence["ok"] is not True and not mutation_evidence.get("reason"):
            mutation_evidence["reason"] = "runtime-recovery-postcondition-failed"

    receipt = _write_automatic_receipt(
        state_root,
        active,
        operation_id=operation_id,
        mutation_evidence=mutation_evidence,
        verified=False,
    )
    if mutation_evidence.get("ok") is not True:
        failed_active = {
            **active,
            "receipt_id": receipt["receipt_id"],
            "receipt_digest": receipt["receipt_digest"],
        }
        return _automatic_failure(
            state_root,
            failed_active,
            reason=str(mutation_evidence.get("reason") or "runtime-recovery-postcondition-failed"),
            verification={"mutation": mutation_evidence},
        )

    verifying = {
        **active,
        "state": "verifying",
        "receipt_id": receipt["receipt_id"],
        "receipt_digest": receipt["receipt_digest"],
        "verified": False,
        "verification_started_at": utc_stamp(datetime.now(timezone.utc)),
        "reason": None,
    }
    _atomic_private(_active_path(state_root, incident_id), verifying)
    _history(state_root, "verifying", verifying)
    return {
        "result": "verifying",
        "verified": False,
        "incident_id": incident_id,
        "receipt_id": receipt["receipt_id"],
    }


def _resume_automatic_runtime_recovery(
    state_root: Path,
    incident_id: str,
    *,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    driver: RuntimeRollbackDriver | None = None,
) -> dict[str, Any]:
    active = _read(_active_path(state_root, incident_id))
    if active is None or active.get("state") != "recovering" or active.get("automatic_authority") is not True:
        return {"result": "refused", "reason": "automatic-recovery-not-resumable"}
    operation_id = str(active.get("operation_id") or "")
    try:
        operation_lock = _try_lock_automatic_operation(state_root, operation_id)
    except OSError:
        return _automatic_failure(
            state_root,
            active,
            reason="automatic-operation-claim-invalid",
        )
    if operation_lock is None:
        return _automatic_operation_in_progress(active)
    try:
        return _resume_automatic_runtime_recovery_locked(
            state_root,
            incident_id,
            runtime_root=runtime_root,
            proc_root=proc_root,
            driver=driver,
        )
    finally:
        operation_lock.close()


def execute_automatic_runtime_recovery(
    state_root: Path,
    incident_id: str,
    *,
    db_root: Path,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    fs_root: Path = Path("/"),
    uid: int | None = None,
    driver: RuntimeRollbackDriver | None = None,
    expected_proposal_id: str | None = None,
) -> dict[str, Any]:
    existing = _read(_active_path(state_root, incident_id))
    if existing is not None and existing.get("automatic_authority") is True:
        if existing.get("state") == "recovering":
            return _resume_automatic_runtime_recovery(
                state_root, incident_id, runtime_root=runtime_root, proc_root=proc_root, driver=driver,
            )
        if existing.get("state") == "verifying":
            return verify_automatic_runtime_recovery(
                state_root, incident_id, runtime_root=runtime_root, proc_root=proc_root,
            )
        if existing.get("state") == "recovered":
            return {
                "result": "recovered",
                "verified": True,
                "incident_id": incident_id,
                "receipt_id": existing.get("receipt_id"),
                "idempotent": True,
            }
        if existing.get("state") == "verification-failed":
            return {
                "result": "verification-failed",
                "verified": False,
                "incident_id": incident_id,
                "receipt_id": existing.get("receipt_id"),
                "idempotent": True,
            }
        if existing.get("state") == "evidence-insufficient":
            return {
                "result": "evidence-insufficient",
                "verified": False,
                "incident_id": incident_id,
                "reason": existing.get("reason"),
                "idempotent": True,
            }

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
        return {
            "result": "refused",
            "reason": proposal.get("reason") or "recovery-proposal-unavailable",
            "incident_id": incident_id,
        }
    if expected_proposal_id is not None and proposal.get("proposal_id") != expected_proposal_id:
        return {
            "result": "refused",
            "reason": "recovery-proposal-binding-drift",
            "incident_id": incident_id,
            "expected_proposal_id": expected_proposal_id,
            "observed_proposal_id": proposal.get("proposal_id"),
        }
    decision = automatic_recovery_policy(state_root, proposal, proc_root=proc_root)
    if decision.get("allowed") is not True:
        pending = {
            **proposal,
            "automatic_decision": decision,
            "automatic_authority": False,
        }
        _atomic_private(_active_path(state_root, incident_id), pending)
        return {
            "result": "refused",
            "reason": "automatic-policy-denied",
            "incident_id": incident_id,
            "automatic_decision": decision,
        }

    evidence = _preserve_automatic_evidence(state_root, proposal, decision)
    operation_id = _automatic_operation_id(proposal, evidence)
    claimed, previous_claim = _claim_automatic_operation(
        state_root,
        operation_id,
        incident_id=incident_id,
        proposal_id=str(proposal["proposal_id"]),
        evidence_snapshot_digest=str(evidence["evidence_snapshot_digest"]),
    )
    if not claimed:
        active = _read(_active_path(state_root, incident_id))
        if (
            active is not None
            and active.get("operation_id") == operation_id
            and active.get("automatic_authority") is True
        ):
            if active.get("state") == "recovering":
                return _resume_automatic_runtime_recovery(
                    state_root, incident_id, runtime_root=runtime_root, proc_root=proc_root, driver=driver,
                )
            if active.get("state") == "verifying":
                return verify_automatic_runtime_recovery(
                    state_root, incident_id, runtime_root=runtime_root, proc_root=proc_root,
                )
            if active.get("state") == "recovered":
                return {
                    "result": "recovered",
                    "verified": True,
                    "incident_id": incident_id,
                    "receipt_id": active.get("receipt_id"),
                    "idempotent": True,
                }
        claim_matches = bool(
            isinstance(previous_claim, Mapping)
            and previous_claim.get("operation_id") == operation_id
            and previous_claim.get("incident_id") == incident_id
            and previous_claim.get("proposal_id") == proposal.get("proposal_id")
            and previous_claim.get("evidence_snapshot_digest")
                == evidence.get("evidence_snapshot_digest")
        )
        if not claim_matches:
            return {
                "result": "refused",
                "reason": "automatic-operation-already-claimed",
                "incident_id": incident_id,
                "claim": previous_claim,
            }

    recovering = {
        **proposal,
        "state": "recovering",
        "authorization_required": False,
        "automatic_authority": True,
        "automatic_decision": decision,
        "operation_id": operation_id,
        "authority_id": operation_id,
        "evidence_snapshot_digest": evidence["evidence_snapshot_digest"],
        "recovery_started_at": str(
            (previous_claim or {}).get("claimed_at")
            if not claimed and isinstance(previous_claim, Mapping)
            else utc_stamp(datetime.now(timezone.utc))
        ),
        "verified": False,
        "exposure": decision.get("exposure"),
    }
    try:
        operation_lock = _try_lock_automatic_operation(state_root, operation_id)
    except OSError:
        return _automatic_failure(
            state_root,
            recovering,
            reason="automatic-operation-claim-invalid",
        )
    if operation_lock is None:
        return _automatic_operation_in_progress(recovering)
    try:
        current = _read(_active_path(state_root, incident_id))
        if (
            current is not None
            and current.get("operation_id") == operation_id
            and current.get("automatic_authority") is True
        ):
            if current.get("state") == "recovering":
                return _resume_automatic_runtime_recovery_locked(
                    state_root,
                    incident_id,
                    runtime_root=runtime_root,
                    proc_root=proc_root,
                    driver=driver,
                )
            if current.get("state") in {
                "verifying", "recovered", "verification-failed", "evidence-insufficient",
            }:
                return {
                    "result": current.get("state"),
                    "verified": current.get("state") == "recovered",
                    "incident_id": incident_id,
                    "receipt_id": current.get("receipt_id"),
                    "idempotent": True,
                }
        _atomic_private(_active_path(state_root, incident_id), recovering)
        _history(state_root, "recovering", recovering)
        _notify_once(
            state_root,
            incident_id,
            "started",
            title="Maho Guardian",
            body="System damage detected. Recovering trusted runtime.",
        )
        return _resume_automatic_runtime_recovery_locked(
            state_root,
            incident_id,
            runtime_root=runtime_root,
            proc_root=proc_root,
            driver=driver,
        )
    finally:
        operation_lock.close()


def verify_automatic_runtime_recovery(
    state_root: Path,
    incident_id: str,
    *,
    runtime_root: Path,
    proc_root: Path = Path("/proc"),
    now: datetime | None = None,
) -> dict[str, Any]:
    active = _read(_active_path(state_root, incident_id))
    if active is None or active.get("state") != "verifying" or active.get("automatic_authority") is not True:
        return {"result": "refused", "reason": "automatic-verification-not-active"}
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    receipt_id = str(active.get("receipt_id") or "")
    receipt = _recovery_receipt_valid(state_root, receipt_id)
    if receipt is None:
        return _automatic_failure(
            state_root,
            active,
            reason="recovery-receipt-invalid",
        )
    mutation = receipt.get("evidence") if isinstance(receipt.get("evidence"), Mapping) else {}
    if mutation.get("ok") is not True:
        return _automatic_failure(
            state_root,
            active,
            reason="runtime-mutation-not-verified",
            verification={"mutation": dict(mutation)},
        )

    rotation = _verify_runtime_rotation(runtime_root, active)
    if rotation.get("ok") is not True:
        return _automatic_failure(
            state_root,
            active,
            reason=str(rotation.get("reason") or "runtime-postcondition-failed"),
            verification={"runtime": rotation},
        )

    try:
        expected_boot_id = (proc_root / "sys/kernel/random/boot_id").read_text(encoding="utf-8").strip() or None
    except OSError:
        expected_boot_id = None
    providers, provider_reasons = _automatic_provider_snapshot(
        state_root,
        now=current,
        expected_boot_id=expected_boot_id,
    )
    started = None
    try:
        started = parse_timestamp(str(active.get("recovery_started_at")))
    except ValueError:
        started = None
    post_observer_reasons: list[str] = []
    if started is None:
        post_observer_reasons.append("recovery-start-time-invalid")
    else:
        for provider_id in AUTO_POST_RECOVERY_OBSERVERS:
            row = providers.get(provider_id) if isinstance(providers, Mapping) else None
            observed = None
            if isinstance(row, Mapping) and row.get("last_success_at"):
                try:
                    observed = parse_timestamp(str(row.get("last_success_at")))
                except ValueError:
                    observed = None
            if observed is None or observed <= started:
                post_observer_reasons.append(f"provider-not-reobserved:{provider_id}")

    source = _source_incident(state_root, incident_id)
    incident_resolved = source is None or source.get("status") not in {None, "active"}
    assessment = _read(state_root / "guardian" / "active" / f"{incident_id}.json")
    assessment_resolved = assessment is None or assessment.get("status") != "active"
    containment = _read(_containment_path(state_root, incident_id))
    containment_clear = containment is None or containment.get("state") not in {
        "containing", "contained", "releasing"
    }
    waiting = list(provider_reasons) + post_observer_reasons
    if not incident_resolved:
        waiting.append("runtime-incident-still-active")
    if not assessment_resolved:
        waiting.append("guardian-assessment-still-active")
    if not containment_clear:
        waiting.append("containment-target-still-active")

    verification = {
        "runtime_rotation": rotation,
        "providers": providers,
        "provider_reasons": list(provider_reasons),
        "post_recovery_observer_reasons": post_observer_reasons,
        "incident_resolved": incident_resolved,
        "guardian_assessment_resolved": assessment_resolved,
        "containment_clear": containment_clear,
        "checked_at": utc_stamp(current),
        "waiting_reasons": list(dict.fromkeys(waiting)),
        "global_trust_promoted": False,
        "exposure": active.get("exposure"),
    }
    if not waiting:
        final_receipt = _write_automatic_receipt(
            state_root,
            active,
            operation_id=str(active.get("operation_id") or ""),
            mutation_evidence=mutation,
            verified=True,
            verification=verification,
        )
        completed = {
            **active,
            "state": "recovered",
            "verified": True,
            "receipt_id": final_receipt["receipt_id"],
            "receipt_digest": final_receipt["receipt_digest"],
            "verification": verification,
            "recovered_at": utc_stamp(current),
            "reason": None,
        }
        _atomic_private(_active_path(state_root, incident_id), completed)
        _history(state_root, "recovered", completed)
        _notify_once(
            state_root,
            incident_id,
            "recovered",
            title="Maho Guardian",
            body="Runtime recovered and verified.",
        )
        return {
            "result": "recovered",
            "verified": True,
            "incident_id": incident_id,
            "receipt_id": final_receipt["receipt_id"],
        }

    elapsed = None
    if started is not None:
        elapsed = (current - started).total_seconds()
    if elapsed is not None and elapsed > AUTO_VERIFICATION_TIMEOUT_SECONDS:
        return _automatic_failure(
            state_root,
            active,
            reason="automatic-verification-timeout",
            verification=verification,
        )

    pending = {
        **active,
        "verification": verification,
        "reason": "waiting-for-independent-reobservation",
    }
    _atomic_private(_active_path(state_root, incident_id), pending)
    return {
        "result": "verifying",
        "verified": False,
        "incident_id": incident_id,
        "receipt_id": receipt_id,
        "waiting_reasons": verification["waiting_reasons"],
    }


def response_projection(state_root: Path) -> dict[str, Any]:
    active_dir = _root(state_root) / "active"
    rows: list[dict[str, Any]] = []
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("inc-*.json")):
            row = _read(path)
            if row is not None:
                rows.append(row)
    priority = {
        "verification-failed": 90,
        "evidence-insufficient": 85,
        "recovering": 80,
        "verifying": 70,
        "authorization-required": 60,
        "recovered": 20,
    }
    selected = max(rows, key=lambda row: priority.get(str(row.get("state")), 0), default=None)
    if selected is None:
        return {
            "backend_state": "NONE",
            "incident_id": None,
            "wheel_spinning": False,
            "outcome": None,
            "stages": {
                "prevent": {"state": "not-applicable", "detail": None},
                "contain": {"state": "not-applicable", "detail": None},
                "recover": {"state": "waiting", "detail": None},
                "verify": {"state": "waiting", "detail": None},
            },
        }
    state = str(selected.get("state") or "none")
    trigger = selected.get("trigger") if isinstance(selected.get("trigger"), Mapping) else {}
    runtime_direct = trigger.get("kind") == "immutable-runtime-integrity"
    canonical = {
        "authorization-required": "NEEDS_AUTHORIZATION",
        "recovering": "RECOVERING",
        "verifying": "VERIFYING",
        "recovered": "RECOVERED",
        "verification-failed": "VERIFICATION_FAILED",
        "evidence-insufficient": "EVIDENCE_INSUFFICIENT",
    }.get(state, state.upper().replace("-", "_"))
    recover_state = "waiting"
    recover_detail = None
    verify_state = "waiting"
    verify_detail = None
    if state == "authorization-required":
        recover_state = "needs-authorization"
        recover_detail = "Automatic policy did not prove mutation safe."
    elif state == "recovering":
        recover_state = "active"
        recover_detail = "Restoring trusted runtime..."
    elif state == "verifying":
        recover_state = "complete"
        verify_state = "active"
        verify_detail = "Verifying recovered runtime..."
    elif state == "recovered":
        recover_state = "complete"
        verify_state = "complete"
    elif state == "verification-failed":
        recover_state = "complete" if selected.get("receipt_id") else "failed"
        verify_state = "failed"
        verify_detail = selected.get("reason")
    elif state == "evidence-insufficient":
        recover_state = "blocked"
        recover_detail = "Current evidence no longer authorizes automatic mutation."
        verify_state = "waiting"
    return {
        "backend_state": canonical,
        "incident_id": selected.get("incident_id"),
        "wheel_spinning": state in {"recovering", "verifying"},
        "outcome": "recovered" if state == "recovered" else (
            "review-required" if state in {"verification-failed", "evidence-insufficient"} else None
        ),
        "automatic_authority": selected.get("automatic_authority") is True,
        "receipt_id": selected.get("receipt_id"),
        "exposure": selected.get("exposure"),
        "stages": {
            "prevent": {
                "state": "not-applicable" if runtime_direct else "bypassed",
                "detail": None,
            },
            "contain": {
                "state": "not-applicable" if runtime_direct else (
                    "complete" if selected.get("containment_receipt_id") else "waiting"
                ),
                "detail": None,
            },
            "recover": {"state": recover_state, "detail": recover_detail},
            "verify": {"state": verify_state, "detail": verify_detail},
        },
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

    active_dir = _root(state_root) / "active"
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("inc-*.json")):
            row = _read(path)
            if (
                row is not None
                and row.get("automatic_authority") is True
                and row.get("state") in {"recovering", "verifying"}
            ):
                incident_ids.add(path.stem)

    results: list[dict[str, Any]] = []
    for incident_id in sorted(incident_ids):
        current = _read(_active_path(state_root, incident_id))
        if current is not None and current.get("automatic_authority") is True:
            if current.get("state") == "recovering":
                result = _resume_automatic_runtime_recovery(
                    state_root,
                    incident_id,
                    runtime_root=runtime_root,
                )
                results.append(_read(_active_path(state_root, incident_id)) or result)
                continue
            if current.get("state") == "verifying":
                result = verify_automatic_runtime_recovery(
                    state_root,
                    incident_id,
                    runtime_root=runtime_root,
                    proc_root=proc_root,
                )
                results.append(_read(_active_path(state_root, incident_id)) or result)
                continue
            if current.get("state") in {"recovered", "verification-failed", "evidence-insufficient"}:
                results.append(current)
                continue
        elif current is not None and current.get("state") in {
            "recovering", "verifying", "recovered", "verification-failed", "evidence-insufficient",
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
        if proposal.get("state") != "authorization-required":
            continue
        decision = automatic_recovery_policy(state_root, proposal, proc_root=proc_root)
        if decision.get("allowed") is True:
            execute_automatic_runtime_recovery(
                state_root,
                incident_id,
                db_root=db_root,
                runtime_root=runtime_root,
                proc_root=proc_root,
                fs_root=fs_root,
                uid=uid,
                expected_proposal_id=str(proposal.get("proposal_id") or ""),
            )
            results.append(_read(_active_path(state_root, incident_id)) or proposal)
        else:
            pending = {
                **proposal,
                "automatic_decision": decision,
                "automatic_authority": False,
            }
            _atomic_private(_active_path(state_root, incident_id), pending)
            results.append(pending)
    status = recovery_status(state_root)
    return {
        "state": status["state"],
        "active": results,
        "automatic_authority": status["automatic_authority"],
        "response": response_projection(state_root),
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
