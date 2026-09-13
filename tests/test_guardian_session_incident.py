#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_incident import list_guardian  # noqa: E402
from guardian_session_incident import (  # noqa: E402
    CORRELATION_WINDOW_SECONDS,
    MIN_DISTINCT_SERVICES,
    project_guardian_rows,
    reconcile_service_session,
)

BOOT_A = "a" * 32
BOOT_B = "b" * 32


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def write_child(root: Path, iid: str, unit: str, second: int, *, boot: str = BOOT_A) -> dict:
    row = {
        "version": 1,
        "kind": "guardian-service-assessment",
        "incident_id": iid,
        "source_kind": "systemd-user-service",
        "status": "active",
        "subject": {"type": "service", "id": unit},
        "normalized": {
            "incident": {
                "scope": "component", "ownership": "maho", "impact": "degraded",
                "evidence_confidence": "confirmed", "persistent": True,
                "occurrence_count": 1, "correlated_failures": 0, "resolved": False,
            },
            "recovery": {"confidence": "certified", "certified_path": True, "previous_failures": 0, "verified": False},
            "context": {"maintenance": False, "expected_transition": False},
        },
        "decision": {"severity": {"level": 2, "label": "component"}, "execution_mode": "diagnose", "recovery": {"action": "diagnose-service-incident"}},
        "service_recovery": {
            "unit": unit, "boot_id": boot, "lifecycle": "unresolved",
            "failed_invocation_id": (iid[-1:] or "1") * 32,
        },
        "opened_at": f"2026-09-12T16:00:{second:02d}+00:00",
        "updated_at": f"2026-09-12T16:00:{second:02d}+00:00",
    }
    active = root / "guardian" / "active"
    active.mkdir(parents=True, exist_ok=True)
    (active / f"{iid}.json").write_text(json.dumps(row))
    return row


def parent_files(root: Path) -> list[Path]:
    return sorted((root / "guardian" / "active").glob("inc-session-*.json"))


def main() -> None:
    watcher = (ROOT / "lib/guardian_service_watcher.py").read_text()
    check("watcher reconciles the session aggregate after observations", watcher.count("reconcile_service_session(") >= 3)
    check("aggregation threshold is independent services, not repetitions", MIN_DISTINCT_SERVICES == 3)
    check("correlation window is bounded", CORRELATION_WINDOW_SECONDS == 30.0)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i in range(10):
            write_child(root, f"inc-service-notify-{i}", "maho-notify.service", i)
        check("ten failures from one service never manufacture L3", reconcile_service_session(root, now=1000.0) is None and not parent_files(root))
        repeated = list_guardian(root)
        check("ten same-service incidents render as one component row", len(repeated) == 1 and repeated[0]["presentation_group"]["incident_count"] == 10)
        out = subprocess.run(
            [sys.executable, str(ROOT / "lib/guardian_explain.py"), "--state-root", str(root)],
            check=True, text=True, capture_output=True,
        ).stdout
        check("same-service loop summary stays readable", "10 unresolved failed invocations" in out and "1 active incident · highest L2" in out)
        child = subprocess.run(
            [sys.executable, str(ROOT / "lib/guardian_explain.py"), "--state-root", str(root), "--incident", "inc-service-notify-0", "--verbose"],
            check=True, text=True, capture_output=True,
        ).stdout
        check("grouped child remains directly inspectable", "inc-service-notify-0" in child and "What happened" in child)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_child(root, "inc-service-shell", "maho-shell.service", 0)
        write_child(root, "inc-service-dock", "maho-dock.service", 10)
        check("two independent failed components remain L2", reconcile_service_session(root, now=1000.0) is None)
        write_child(root, "inc-service-notify", "maho-notify.service", 59)
        check("widely separated failures do not correlate into L3", reconcile_service_session(root, now=1000.0) is None)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        one = write_child(root, "inc-service-shell", "maho-shell.service", 0)
        two = write_child(root, "inc-service-dock", "maho-dock.service", 4)
        three = write_child(root, "inc-service-notify", "maho-notify.service", 8)
        parent = reconcile_service_session(root, now=1000.0)
        check("three independent failed recoveries create one session parent", parent is not None and len(parent_files(root)) == 1)
        check("derived parent reaches real Guardian L3", parent["decision"]["severity"]["level"] == 3 and parent["decision"]["severity"]["label"] == "session")
        check("session parent cannot invent broader automatic mutation", parent["decision"]["mutating_recovery_allowed"] is False)
        failure = parent["session_failure"]
        check("parent records exact affected services", failure["affected_units"] == ["maho-dock.service", "maho-notify.service", "maho-shell.service"])
        check("parent records child identities", set(failure["child_incident_ids"]) == {one["incident_id"], two["incident_id"], three["incident_id"]})
        check("L3 correlation count means independent peers", parent["normalized"]["incident"]["correlated_failures"] == 2)

        unrelated = {
            "version": 1, "kind": "guardian-security-assessment", "incident_id": "inc-host-unrelated",
            "status": "active", "subject": {"type": "host", "id": "local"},
            "decision": {"severity": {"level": 1, "label": "minor"}, "recovery": {"action": "diagnose-only"}},
            "opened_at": "2026-09-12T16:00:09+00:00",
        }
        (root / "guardian" / "active" / "inc-host-unrelated.json").write_text(json.dumps(unrelated))
        rows = [json.loads(path.read_text()) for path in (root / "guardian" / "active").glob("*.json")]
        projected = project_guardian_rows(rows)
        check("presentation collapses child L2s under L3 parent", len(projected) == 2 and any(r.get("kind") == "guardian-session-assessment" for r in projected))
        check("session projection never hides unrelated incidents", any(r.get("incident_id") == "inc-host-unrelated" for r in projected))
        listed = list_guardian(root)
        check("guardian-status hides only aggregated children", len(listed) == 2 and listed[0]["incident_id"] == parent["incident_id"] and any(r["incident_id"] == "inc-host-unrelated" for r in listed))
        active_dir = root / "guardian" / "active"
        check("derived parent state stays private", (os.stat(active_dir).st_mode & 0o077) == 0 and (os.stat(parent_files(root)[0]).st_mode & 0o077) == 0)

        out = subprocess.run(
            [sys.executable, str(ROOT / "lib/guardian_explain.py"), "--state-root", str(root)],
            check=True, text=True, capture_output=True,
        ).stdout
        check("default why stays compact around one L3 parent", "2 active incidents · highest L3" in out and "3 independent Maho services" in out)
        check("default why names affected services", "maho-shell.service" in out and "maho-dock.service" in out and "maho-notify.service" in out)
        check("default why does not dump child incidents", "inc-service-shell" not in out and "inc-service-dock" not in out)

        (root / "guardian" / "active" / "inc-service-notify.json").unlink()
        resolved = reconcile_service_session(root, now=1010.0)
        check("session parent clears when correlation drops below threshold", resolved is None and not parent_files(root))
        archive = list((root / "guardian" / "archive").glob("inc-session-*-resolved.json"))
        check("cleared parent is archived instead of deleted", len(archive) == 1 and json.loads(archive[0].read_text())["resolution"]["kind"] == "session-correlation-cleared")
        remaining = list_guardian(root)
        check("remaining component L2s become visible again", {r["incident_id"] for r in remaining} == {"inc-service-shell", "inc-service-dock", "inc-host-unrelated"})

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        for i, unit in enumerate(("maho-shell.service", "maho-dock.service", "maho-notify.service")):
            write_child(root, f"inc-service-a-{i}", unit, i, boot=BOOT_A)
        first = reconcile_service_session(root, now=1000.0)
        for path in (root / "guardian" / "active").glob("inc-service-*.json"):
            path.unlink()
        for i, unit in enumerate(("maho-shell.service", "maho-dock.service", "maho-wallpaper.service")):
            write_child(root, f"inc-service-b-{i}", unit, i, boot=BOOT_B)
        second = reconcile_service_session(root, now=2000.0)
        check("new boot replaces stale session parent", first and second and first["incident_id"] != second["incident_id"] and len(parent_files(root)) == 1)
        check("stale session parent is archived across boot boundary", bool(list((root / "guardian" / "archive").glob(f"{first['incident_id']}-*-resolved.json"))))

    print("ALL GUARDIAN SESSION AGGREGATION TESTS PASS")


if __name__ == "__main__":
    main()
