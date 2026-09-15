#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_live_state import render_status  # noqa: E402


def main() -> None:
    payload = {
        "world_state": {"guardian": {"severity": {"level": 0, "label": "normal"}, "trust": {"state": "UNKNOWN"}, "self_health": {"state": "DEGRADED"}}},
        "system": {"current_system_generation": None, "current_kernel_generation": None},
        "boot": {"boot_id": "boot-a", "kernel_release": "test"},
        "recovery": {"current_generation_trust": "UNRESOLVED"},
        "active_incidents": [],
        "containment": {"state": "none"},
        "evidence_freshness": {"security.integrity": {"freshness": "stale", "health": "healthy"}},
        "authorized_operation_evidence": [],
        "errors": [],
    }
    output = render_status(payload)
    required = ("System", "Trust", "Guardian self-health", "Boot", "Recovery", "Active incidents", "Evidence freshness")
    if not all(item in output for item in required):
        raise AssertionError("plain technical status is incomplete")
    if "score" in output.lower() or "dashboard" in output.lower():
        raise AssertionError("status introduced a fake score/dashboard surface")
    print("PASS canonical plain status surface")


if __name__ == "__main__":
    main()
