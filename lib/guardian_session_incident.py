#!/usr/bin/env python3
"""Derive one session-level Guardian incident from independent service failures.

Component incidents remain the source of truth. This module never mutates or
restarts services; it only derives a bounded parent assessment for presentation
and escalation when multiple certified Maho services exhaust delegated recovery.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from guardian_engine import evaluate_guardian
from guardian_service_incident import _atomic_private

VERSION = 1
MIN_DISTINCT_SERVICES = 3
CORRELATION_WINDOW_SECONDS = 30.0
SESSION_SUBJECT = "maho-user-session"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text())
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _stamp(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat()


def _incident_id(boot_id: str) -> str:
    digest = hashlib.sha256(f"session:{boot_id}:{SESSION_SUBJECT}".encode()).hexdigest()[:20]
    return f"inc-session-{digest}"


def _active_service_rows(guardian_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in (guardian_root / "active").glob("inc-service-*.json"):
        row = _read(path)
        service = (row or {}).get("service_recovery") or {}
        if (
            row
            and row.get("status") == "active"
            and service.get("lifecycle") == "unresolved"
            and isinstance(service.get("unit"), str)
            and isinstance(service.get("boot_id"), str)
        ):
            rows.append(row)
    return rows


def _candidate(rows: list[dict[str, Any]]) -> tuple[str, list[str], list[dict[str, Any]]] | None:
    by_boot: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        boot = str((row.get("service_recovery") or {}).get("boot_id") or "")
        if boot:
            by_boot.setdefault(boot, []).append(row)

    candidates: list[tuple[float, str, list[str], list[dict[str, Any]]]] = []
    for boot, boot_rows in by_boot.items():
        latest_by_unit: dict[str, tuple[float, dict[str, Any]]] = {}
        for row in boot_rows:
            service = row.get("service_recovery") or {}
            unit = str(service.get("unit") or "")
            when = _epoch(row.get("opened_at") or service.get("opened_at"))
            if not unit or when is None:
                continue
            previous = latest_by_unit.get(unit)
            if previous is None or when > previous[0]:
                latest_by_unit[unit] = (when, row)
        if not latest_by_unit:
            continue
        latest = max(value[0] for value in latest_by_unit.values())
        units = sorted(
            unit for unit, (when, _) in latest_by_unit.items()
            if latest - when <= CORRELATION_WINDOW_SECONDS
        )
        if len(units) < MIN_DISTINCT_SERVICES:
            continue
        affected = set(units)
        children = [
            row for row in boot_rows
            if str((row.get("service_recovery") or {}).get("unit") or "") in affected
        ]
        candidates.append((latest, boot, units, children))
    if not candidates:
        return None
    _, boot, units, children = max(candidates, key=lambda item: item[0])
    return boot, units, children


def _normalized(units: list[str], children: list[dict[str, Any]], *, resolved: bool) -> dict[str, Any]:
    return {
        "incident": {
            "scope": "session",
            "ownership": "maho",
            "impact": "degraded",
            "evidence_confidence": "confirmed",
            "persistent": not resolved,
            "occurrence_count": 0 if resolved else len(children),
            "correlated_failures": max(0, len(units) - 1),
            "resolved": resolved,
        },
        "recovery": {
            "confidence": "high",
            "certified_path": False,
            "previous_failures": len(units),
            "verified": resolved,
        },
        "context": {"maintenance": False, "expected_transition": False},
    }


def _decision(normalized: Mapping[str, Any]) -> dict[str, Any]:
    # A session aggregate establishes severity, not permission to widen recovery.
    # Until a live session -> L3 provider binding exists, remain non-mutating.
    recovery_state = {
        "failure": {
            "domain": "system-userspace",
            "graphical_available": True,
            "transaction_in_progress": False,
        },
        "availability": {},
    }
    return evaluate_guardian(normalized, recovery_state).as_dict()


def _semantic(row: Mapping[str, Any]) -> tuple[Any, ...]:
    failure = row.get("session_failure") or {}
    decision = row.get("decision") or {}
    severity = decision.get("severity") or {}
    recovery = decision.get("recovery") or {}
    return (
        row.get("status"),
        tuple(failure.get("affected_units") or ()),
        tuple(failure.get("child_incident_ids") or ()),
        failure.get("unresolved_failures"),
        severity.get("level"),
        recovery.get("action"),
    )


def _archive_parent(path: Path, archive: Path, current: Mapping[str, Any], moment: float) -> None:
    units = list((current.get("session_failure") or {}).get("affected_units") or [])
    normalized = _normalized(units, [], resolved=True)
    resolved = dict(current)
    resolved.update({
        "status": "resolved",
        "normalized": normalized,
        "decision": _decision(normalized),
        "updated_at": _stamp(moment),
        "resolved_at": _stamp(moment),
        "resolution": {"kind": "session-correlation-cleared"},
    })
    _atomic_private(archive / f"{path.stem}-{int(moment)}-resolved.json", resolved)
    path.unlink(missing_ok=True)


def reconcile_service_session(state_root: Path, *, now: float | None = None) -> dict[str, Any] | None:
    import time

    moment = time.time() if now is None else now
    guardian = state_root / "guardian"
    active = guardian / "active"
    archive = guardian / "archive"
    active.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    rows = _active_service_rows(guardian)
    candidate = _candidate(rows)
    existing = [p for p in active.glob("inc-session-*.json") if p.is_file()]

    if candidate is None:
        for path in existing:
            current = _read(path)
            if not current:
                path.unlink(missing_ok=True)
                continue
            _archive_parent(path, archive, current, moment)
        return None

    boot_id, units, children = candidate
    iid = _incident_id(boot_id)
    path = active / f"{iid}.json"
    for stale in existing:
        if stale == path:
            continue
        current = _read(stale)
        if current:
            _archive_parent(stale, archive, current, moment)
        else:
            stale.unlink(missing_ok=True)
    old = _read(path)
    child_ids = sorted(str(row.get("incident_id")) for row in children if row.get("incident_id"))
    opened = min(
        (str(row.get("opened_at")) for row in children if row.get("opened_at")),
        default=_stamp(moment),
    )
    normalized = _normalized(units, children, resolved=False)
    row = {
        "version": VERSION,
        "kind": "guardian-session-assessment",
        "incident_id": iid,
        "source_kind": "correlated-systemd-user-services",
        "status": "active",
        "subject": {"type": "session", "id": SESSION_SUBJECT},
        "normalized": normalized,
        "decision": _decision(normalized),
        "session_failure": {
            "boot_id": boot_id,
            "affected_units": units,
            "distinct_services": len(units),
            "unresolved_failures": len(children),
            "child_incident_ids": child_ids,
            "correlation_window_seconds": CORRELATION_WINDOW_SECONDS,
        },
        "opened_at": (old or {}).get("opened_at") or opened,
        "updated_at": _stamp(moment),
        "resolved_at": None,
    }
    if old and _semantic(old) == _semantic(row):
        return old
    _atomic_private(path, row)
    return row


def project_guardian_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Present one row per fault domain without deleting underlying incidents.

    An active session parent suppresses its component children. Otherwise repeated
    failures from one service are grouped into one representative component row.
    """
    hidden: set[str] = set()
    for row in rows:
        if row.get("status") != "active" or row.get("kind") != "guardian-session-assessment":
            continue
        failure = row.get("session_failure") or {}
        hidden.update(str(value) for value in failure.get("child_incident_ids") or [] if value)

    visible = [row for row in rows if str(row.get("incident_id") or "") not in hidden]
    service_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in visible:
        service = row.get("service_recovery") or {}
        unit = service.get("unit")
        boot = service.get("boot_id")
        if row.get("kind") == "guardian-service-assessment" and isinstance(unit, str) and isinstance(boot, str):
            service_groups.setdefault((boot, unit), []).append(row)
        else:
            passthrough.append(row)

    for (boot, unit), group in service_groups.items():
        if len(group) == 1:
            passthrough.append(group[0])
            continue
        representative = max(
            group,
            key=lambda row: (
                int((((row.get("decision") or {}).get("severity") or {}).get("level") or 0)),
                str(row.get("updated_at") or row.get("opened_at") or ""),
            ),
        )
        projected = dict(representative)
        projected["presentation_group"] = {
            "kind": "service-failure-series",
            "boot_id": boot,
            "unit": unit,
            "incident_count": len(group),
            "child_incident_ids": sorted(
                str(row.get("incident_id")) for row in group if row.get("incident_id")
            ),
        }
        passthrough.append(projected)
    return passthrough
