#!/usr/bin/env python3
"""Bounded Guardian projection of kernel prevention evidence."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Mapping

from guardian_evidence import parse_timestamp


_REQUIRED = {
    "schema_version", "kind", "observed_at", "boot_id", "subject", "target",
    "effect_mask", "operation_mask", "policy_reason", "authority_state",
    "result", "host_mutation_performed", "compromise_evidence",
}


def _valid(row: Any) -> bool:
    if not isinstance(row, Mapping) or set(row) != _REQUIRED:
        return False
    subject, target = row.get("subject"), row.get("target")
    if not isinstance(subject, Mapping) or not isinstance(target, Mapping):
        return False
    if set(subject) != {"pid", "uid", "start_time_ticks", "executable_device", "executable_inode"}:
        return False
    schema = row.get("schema_version")
    if schema == 1:
        if set(target) != {"device", "inode", "scope_device", "scope_inode"}:
            return False
        target_numbers = tuple(target.values())
    elif schema == 2:
        if set(target) != {"kind", "pid", "start_time_ticks", "executable_device", "executable_inode", "signal"}:
            return False
        if target.get("kind") != "process" or not isinstance(target.get("signal"), int) or not 1 <= target["signal"] <= 64:
            return False
        target_numbers = (
            target["pid"], target["start_time_ticks"],
            target["executable_device"], target["executable_inode"], target["signal"],
        )
    else:
        return False
    return (
        row.get("kind") == "guardian-prevention-event"
        and row.get("result") == "prevented"
        and row.get("host_mutation_performed") is False
        and row.get("compromise_evidence") is False
        and all(isinstance(value, int) and value >= 0 for value in (*subject.values(), *target_numbers, row.get("effect_mask"), row.get("operation_mask")))
    )


def prevention_status(root: Path, *, now: datetime | None = None, limit: int = 50) -> dict[str, Any]:
    path = root / "events.jsonl"
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not path.is_file():
        return {"state": "inactive-or-no-evidence", "prevented_count": 0, "recent": [], "invalid_records": 0, "correlation": {"suspicious": False, "reason": "no_prevention_events"}}
    recent: list[dict[str, Any]] = []
    invalid = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-max(1, min(limit * 4, 1000)):]
    except (OSError, UnicodeError):
        return {"state": "unreadable", "prevented_count": 0, "recent": [], "invalid_records": 1, "correlation": {"suspicious": False, "reason": "evidence_unreadable"}}
    for line in lines:
        try:
            row = json.loads(line)
            stamp = parse_timestamp(row.get("observed_at")) if isinstance(row, Mapping) else None
        except (json.JSONDecodeError, ValueError, TypeError):
            invalid += 1
            continue
        if not _valid(row) or stamp is None:
            invalid += 1
            continue
        if stamp >= current - timedelta(hours=24):
            recent.append(dict(row))
    recent = recent[-limit:]
    subjects: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
    for row in recent:
        subject = row["subject"]
        key = (subject["start_time_ticks"], subject["executable_device"], subject["executable_inode"])
        subjects.setdefault(key, []).append(row)
    suspicious = any(len(rows) >= 3 and len({item["effect_mask"] for item in rows}) >= 2 for rows in subjects.values())
    return {
        "state": "recording", "prevented_count": len(recent), "recent": recent,
        "invalid_records": invalid,
        "correlation": {
            "suspicious": suspicious,
            "reason": "repeated_cross_boundary_attempts" if suspicious else "isolated_or_uncorroborated_prevention",
        },
        "trust_effect": "none",
        "incident_effect": "correlation-input-only" if suspicious else "none",
    }
