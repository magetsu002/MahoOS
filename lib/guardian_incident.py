#!/usr/bin/env python3
"""Normalize real Maho security incidents into Guardian decisions and history.

The security incident engine remains the evidence/correlation authority.
Guardian consumes its durable incident records, derives a normalized severity
view, asks the recovery planner for the permitted recovery scope, and persists
an explanation record. This module never performs the recovery action.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from guardian_engine import evaluate_guardian
from guardian_session_incident import project_guardian_rows


_RISK_IMPACT = {
    "info": "minor",
    "low": "minor",
    "medium": "degraded",
    "high": "degraded",
    "critical": "unavailable",
}
_DURABLE_SIGNAL_KINDS = {
    "confirmed-finding",
    "integrity-drift",
    "persistence-drift",
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _signals(incident: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = incident.get("signals")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _signal_kinds(incident: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("kind"))
        for item in _signals(incident)
        if isinstance(item.get("kind"), str)
    }


def _ownership(subject: Mapping[str, Any]) -> str:
    subject_type = subject.get("type")
    subject_id = subject.get("id")
    if subject_type == "package" and isinstance(subject_id, str):
        # Maho package identity is explicit by package namespace. Generic host
        # and third-party package incidents remain unknown and cannot authorize
        # mutation.
        if subject_id == "maho" or subject_id.startswith("maho-") or subject_id.startswith("mahoos-"):
            return "maho"
    return "unknown"


def _scope(subject: Mapping[str, Any]) -> str:
    if subject.get("type") == "package":
        return "component"
    if subject.get("type") == "host":
        return "system"
    return "unknown"


def _impact(incident: Mapping[str, Any], subject: Mapping[str, Any]) -> str:
    risk = incident.get("risk")
    confidence = incident.get("confidence")
    if subject.get("type") == "host" and risk == "critical" and confidence == "confirmed":
        return "catastrophic"
    return _RISK_IMPACT.get(str(risk), "minor")


def _persistent(incident: Mapping[str, Any]) -> bool:
    # Persistence is semantic: durable evidence remains until the underlying
    # state changes. Re-running a detector does not make an incident "more
    # severe" merely because a counter increased.
    return bool(_signal_kinds(incident) & _DURABLE_SIGNAL_KINDS)


def normalize_security_incident(incident: Mapping[str, Any]) -> dict[str, Any]:
    subject = _mapping(incident.get("subject"))
    confidence = incident.get("confidence")
    if confidence not in {"low", "medium", "high", "confirmed"}:
        confidence = "low"
    resolved = incident.get("status") == "resolved"
    source_diversity = incident.get("source_diversity")
    if not isinstance(source_diversity, int) or isinstance(source_diversity, bool):
        source_diversity = len(
            {
                item.get("source")
                for item in _signals(incident)
                if isinstance(item.get("source"), str)
            }
        )

    return {
        "incident": {
            "scope": _scope(subject),
            "ownership": _ownership(subject),
            "impact": _impact(incident, subject),
            "evidence_confidence": confidence,
            "persistent": _persistent(incident),
            "occurrence_count": 0 if resolved else 1,
            "correlated_failures": max(0, source_diversity - 1),
            "resolved": resolved,
        },
        "recovery": {
            # Security incidents currently have no certified mutating recovery
            # mapping. They remain diagnosis-only until an explicit recovery
            # adapter contract is added.
            "confidence": "none",
            "certified_path": False,
            "previous_failures": 0,
            "verified": resolved,
        },
        "context": {
            "maintenance": False,
            "expected_transition": False,
        },
    }


def security_recovery_state(incident: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "failure": {
            "domain": "unknown",
            "graphical_available": True,
            "transaction_in_progress": False,
        },
        "availability": {},
    }


def evaluate_security_incident(incident: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_security_incident(incident)
    decision = evaluate_guardian(normalized, security_recovery_state(incident))
    subject = _mapping(incident.get("subject"))
    return {
        "version": 1,
        "kind": "guardian-assessment",
        "incident_id": str(incident.get("incident_id") or ""),
        "source_kind": str(incident.get("kind") or "security-incident"),
        "status": "resolved" if incident.get("status") == "resolved" else "active",
        "subject": dict(subject),
        "normalized": normalized,
        "decision": decision.as_dict(),
        "explanation": {
            "incident": (
                f"{subject.get('type', 'unknown')}:{subject.get('id', 'unknown')} "
                f"risk={incident.get('risk', 'unknown')} "
                f"confidence={incident.get('confidence', 'unknown')}"
            ),
            "severity": decision.severity["reason"],
            "recovery": decision.recovery["reason"],
        },
        "opened_at": incident.get("opened_at"),
        "updated_at": incident.get("updated_at"),
        "resolved_at": incident.get("resolved_at"),
    }


def _atomic_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def reconcile_security(state_root: Path, reconcile_result: Mapping[str, Any]) -> dict[str, Any]:
    root = state_root / "guardian"
    active_dir = root / "active"
    archive_dir = root / "archive"
    active_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(active_dir, 0o700)
    os.chmod(archive_dir, 0o700)

    changes: dict[str, list[dict[str, Any]]] = {
        "created": [],
        "updated": [],
        "resolved": [],
    }

    for kind in ("created", "updated", "unchanged"):
        raw_rows = reconcile_result.get(kind)
        if not isinstance(raw_rows, list):
            continue
        for incident in raw_rows:
            if not isinstance(incident, Mapping):
                continue
            record = evaluate_security_incident(incident)
            iid = record["incident_id"]
            if not iid:
                continue
            _atomic_private(
                active_dir / f"{iid}.json",
                (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(),
            )
            if kind in changes:
                changes[kind].append(record)

    raw_resolved = reconcile_result.get("resolved")
    if isinstance(raw_resolved, list):
        for incident in raw_resolved:
            if not isinstance(incident, Mapping):
                continue
            record = evaluate_security_incident(incident)
            iid = record["incident_id"]
            if not iid:
                continue
            stamp = str(incident.get("resolved_at") or incident.get("updated_at") or "resolved")
            safe_stamp = "".join(ch for ch in stamp if ch.isalnum())
            _atomic_private(
                archive_dir / f"{iid}-{safe_stamp}.json",
                (json.dumps(record, indent=2, sort_keys=True) + "\n").encode(),
            )
            try:
                (active_dir / f"{iid}.json").unlink()
            except FileNotFoundError:
                pass
            changes["resolved"].append(record)

    active_records: list[dict[str, Any]] = []
    for path in sorted(active_dir.glob("inc-*.json")):
        try:
            data = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(data, dict):
            active_records.append(data)

    highest_level = max(
        (int(_mapping(_mapping(row.get("decision")).get("severity")).get("level", 0)) for row in active_records),
        default=0,
    )

    return {
        "version": 1,
        "kind": "guardian-security-reconcile",
        "active": len(active_records),
        "highest_level": highest_level,
        "created": changes["created"],
        "updated": changes["updated"],
        "resolved": changes["resolved"],
    }


def list_guardian(state_root: Path) -> list[dict[str, Any]]:
    active_dir = state_root / "guardian" / "active"
    rows: list[dict[str, Any]] = []
    if active_dir.is_dir():
        for path in sorted(active_dir.glob("inc-*.json")):
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            if isinstance(data, dict):
                rows.append(data)
    rows = project_guardian_rows(rows)
    rows.sort(
        key=lambda row: (
            -int(_mapping(_mapping(row.get("decision")).get("severity")).get("level", 0)),
            str(row.get("incident_id") or ""),
        )
    )
    return rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="guardian_incident.py")
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("security-reconcile")
    rec.add_argument("--state-root", required=True)
    rec.add_argument("--input", default="-")
    ls = sub.add_parser("list")
    ls.add_argument("--state-root", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    state_root = Path(args.state_root)
    if args.command == "security-reconcile":
        raw = (
            json.load(os.sys.stdin)
            if args.input == "-"
            else json.loads(Path(args.input).read_text())
        )
        if not isinstance(raw, Mapping):
            raise SystemExit("Guardian reconcile input must be a JSON object")
        print(json.dumps(reconcile_security(state_root, raw), sort_keys=True, separators=(",", ":")))
    elif args.command == "list":
        print(json.dumps(list_guardian(state_root), sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
