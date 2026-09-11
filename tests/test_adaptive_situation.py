#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_situation import UNKNOWN, build_situation

NOW = datetime(2026, 9, 12, 0, 0, tzinfo=timezone.utc)


def envelope(data, observed="2026-09-11T23:59:30Z"):
    return {"observed_at": observed, "data": data}


def main() -> None:
    observations = {
        "power": envelope({"supplies": [
            {"type": "Mains", "online": False, "stable_seconds": 600},
            {"type": "Battery", "present": True, "capacity_percent": 34, "status": "Discharging"},
        ]}),
        "thermal": envelope({"max_millidegree_c": 81234, "sustained_seconds": 90, "trend": "rising"}),
        "session": envelope({"locked": True, "lock_dwell_seconds": 1800, "idle_seconds": 1900, "recent_input_seconds": 1900}),
        "workload": envelope({"probable_compile": True, "interactive": False, "confidence": 0.92, "evidence": ["compiler-tree", "sustained-cpu"]}),
        "network": envelope({"connectivity": "online", "default_route": True, "reachable": True, "stability": "stable", "stability_seconds": 600}),
        "maintenance": envelope({"transaction_state": "PREPARED", "pending": True, "staged": True, "prepared": True, "recovery_prerequisites": True, "in_critical_section": False, "interruption_safe": True, "enough_disk": True}),
        "guardian": envelope({"active_incident": False, "severity_level": 0, "recovery_in_progress": False, "unresolved_reliability": False}),
        "user_intent": envelope({"power_mode": "balanced", "dnd": False, "explicit_maintenance": False, "foreground_performance": False, "adaptation_opt_outs": []}),
        "adaptive_posture": {"active_leases": ["lease-1"], "effective_posture": {"maintenance": "suspended"}, "oldest_lease_age_seconds": 60, "source_policies": ["thermal"]},
    }
    first = build_situation(observations, captured_at=NOW)
    second = build_situation(observations, captured_at=NOW)
    assert first == second
    assert first.snapshot_id == second.snapshot_id
    assert first.power.percentage == 34 and first.power.severity_band == "LOW"
    assert first.thermal.level == "warm"
    assert first.session.locked is True and first.time.session_age_seconds == 1800
    assert first.workload.probable_compile is True and first.workload.confidence == 0.92
    assert first.network.freshness == "fresh"
    assert first.maintenance.transaction_state == "PREPARED"
    assert first.adaptive_posture.effective_posture == (("maintenance", "suspended"),)

    try:
        first.power.percentage = 99  # type: ignore[misc]
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("situation snapshot is mutable")

    partial = build_situation({"power": observations["power"]}, captured_at=NOW)
    assert partial.power.percentage == 34
    assert partial.thermal.level == UNKNOWN
    assert partial.workload.confidence == UNKNOWN
    assert partial.network.connectivity == UNKNOWN

    stale = build_situation({"power": envelope({"percentage": 5, "ac_online": False}, "2026-09-11T23:40:00Z")}, captured_at=NOW)
    assert stale.power.percentage == 5
    assert stale.power.freshness == "stale"
    assert stale.power.age_seconds == 1200.0

    malformed = build_situation({"thermal": envelope({"max_millidegree_c": 9999999}, "not-a-time")}, captured_at=NOW)
    assert malformed.thermal.maximum_millidegree_c == UNKNOWN
    assert malformed.thermal.freshness == UNKNOWN

    print("ALL ADAPTIVE SITUATION TESTS PASS")


if __name__ == "__main__":
    main()
