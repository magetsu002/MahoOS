from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_adaptive_shadow import (
    apply_dwell,
    current_status,
    doctor_report,
    evaluate_shadow,
    history_rows,
)

T0 = datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc)


def stamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def env(data, at=T0):
    return {"observed_at": stamp(at), "data": data}


def fixture(now=T0, *, battery=15, ac=False, thermal=70000, locked=False):
    return {
        "power": env({
            "supplies": [
                {"name": "AC", "type": "Mains", "online": ac},
                {"name": "BAT", "type": "Battery", "present": True,
                 "capacity_percent": battery,
                 "status": "Charging" if ac else "Discharging"},
            ],
            "ac_stable_seconds": 600,
            "drain_trend": "falling" if not ac else "stable",
        }, now),
        "thermal": env({
            "max_millidegree_c": thermal,
            "sustained_seconds": 600,
            "trend": "stable",
            "recent_transitions": [],
        }, now),
        "session": env({
            "locked": locked,
            "lock_dwell_seconds": 1800 if locked else 0,
            "idle_seconds": 1800 if locked else 0,
            "recent_input_seconds": 1800 if locked else 0,
            "inhibitors": [],
        }, now),
        "workload": env({
            "fullscreen": False,
            "probable_gaming": False,
            "probable_compile": False,
            "probable_rendering": False,
            "probable_media": False,
            "interactive": False,
            "high_background_cpu": False,
            "gpu_activity": False,
            "confidence": .95,
            "evidence": [],
        }, now),
        "network": env({
            "connectivity": "online",
            "default_route": True,
            "reachable": True,
            "stability": "stable",
            "stability_seconds": 600,
            "recent_transition": "stable",
        }, now),
        "maintenance": env({
            "transaction_state": "DISCOVERED",
            "pending": True,
            "staged": False,
            "prepared": False,
            "recovery_prerequisites": "unknown",
            "in_critical_section": False,
            "interruption_safe": True,
            "enough_disk": "unknown",
        }, now),
        "guardian": env({
            "active_incident": False,
            "severity_level": 0,
            "recovery_in_progress": False,
            "unresolved_reliability": False,
        }, now),
        "user_intent": env({
            "power_mode": "balanced",
            "adaptation_opt_outs": [],
            "dnd": False,
            "explicit_maintenance": False,
            "foreground_performance": False,
        }, now),
    }


def test_dwell_context() -> None:
    tracker = {"schema_version": 1}
    first = fixture(T0, battery=50, ac=False, thermal=86000, locked=True)
    apply_dwell(first, tracker, T0)
    assert first["session"]["data"]["lock_dwell_seconds"] == 0
    assert first["thermal"]["data"]["sustained_seconds"] == 0
    assert first["network"]["data"]["stability_seconds"] == 0

    later = fixture(T0 + timedelta(seconds=70), battery=48, ac=False, thermal=87000, locked=True)
    apply_dwell(later, tracker, T0 + timedelta(seconds=70))
    assert later["session"]["data"]["lock_dwell_seconds"] == 70
    assert later["thermal"]["data"]["sustained_seconds"] == 70
    assert later["thermal"]["data"]["trend"] == "rising"
    assert later["network"]["data"]["stability_seconds"] == 70
    assert later["power"]["data"]["drain_trend"] in {"falling", "rapid-fall"}

    changed = fixture(T0 + timedelta(seconds=71), battery=48, ac=True, thermal=74000, locked=False)
    apply_dwell(changed, tracker, T0 + timedelta(seconds=71))
    assert changed["session"]["data"]["lock_dwell_seconds"] == 0
    assert changed["thermal"]["data"]["sustained_seconds"] == 0
    assert changed["power"]["data"]["ac_stable_seconds"] == 0


def test_shadow_history_and_leases() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-adaptive-shadow-") as temporary:
        state = Path(temporary)
        first = evaluate_shadow(state, now=T0, observations=fixture(T0))
        assert first["actions"] == {"mode": "SHADOW_ONLY", "mutation_executed": False}
        assert first["meaningful_transition"] is True
        assert first["transition_count"] == 1
        assert first["active_shadow_posture"] == {}
        assert first["proposals"], first
        assert all(lease["mode"] == "shadow" for lease in first["leases"])
        assert all("EXECUTABLE" not in lease["state"] for lease in first["leases"])

        second_time = T0 + timedelta(seconds=30)
        second = evaluate_shadow(state, now=second_time, observations=fixture(second_time))
        assert second["active_shadow_posture"]["maintenance"] == "suspended"
        assert second["active_shadow_posture"]["background_work"] == "reduced"
        assert second["meaningful_transition"] is True
        assert second["transition_count"] == 2
        assert any(lease["state"] == "VERIFIED_SHADOW" for lease in second["leases"])

        third_time = T0 + timedelta(seconds=31)
        third = evaluate_shadow(state, now=third_time, observations=fixture(third_time))
        assert third["meaningful_transition"] is False
        assert third["transition_count"] == 2
        assert len(history_rows(state, 20)) == 2
        assert current_status(state)["semantic_signature"] == third["semantic_signature"]

        with (state / "history.jsonl").open("a", encoding="utf-8") as stream:
            stream.write('{"partial":')
        assert len(history_rows(state, 20)) == 2
        assert history_rows(state, 1)[0]["transition_number"] == 2


def test_corrupt_lease_fail_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-adaptive-corrupt-") as temporary:
        state = Path(temporary)
        state.mkdir(parents=True, exist_ok=True)
        (state / "leases.json").write_text(json.dumps({"schema_version": 1, "leases": [{"bad": True}]}))
        result = evaluate_shadow(state, now=T0, observations=fixture(T0))
        assert str(result["blocked"]).startswith("lease-state-invalid:")
        assert result["active_shadow_posture"] == {}
        assert result["actions"]["mutation_executed"] is False


def test_doctor_and_static_authority() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-adaptive-doctor-") as temporary:
        report = doctor_report(ROOT, Path(temporary))
        assert report["healthy"] is True, report
        assert report["mode"] == "SHADOW_ONLY"
        assert report["service_enabled_by_policy"] is False

    wrapper = (ROOT / "bin/maho-adaptive").read_text()
    unit = (ROOT / "systemd/user/maho-adaptive.service").read_text()
    assert "maho_adaptive_shadow.py" in wrapper
    assert "maho-adaptive watch" in unit
    forbidden = ("sudo", "pacman", "efibootmgr", "reboot", "shutdown", "poweroff", "killall", "pkill")
    combined = wrapper + "\n" + (ROOT / "lib/maho_adaptive_shadow.py").read_text()
    for token in forbidden:
        assert token not in combined, token


def test_frontend_status() -> None:
    with tempfile.TemporaryDirectory(prefix="maho-adaptive-cli-") as temporary:
        state = Path(temporary)
        evaluate_shadow(state, now=T0, observations=fixture(T0))
        result = subprocess.run(
            [str(ROOT / "bin/maho-adaptive"), "--state-root", str(state), "status", "--json"],
            text=True, capture_output=True, check=False,
            env={**dict(__import__("os").environ), "MAHO_ROOT": str(ROOT)},
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["actions"] == {"mode": "SHADOW_ONLY", "mutation_executed": False}


def main() -> None:
    test_dwell_context()
    test_shadow_history_and_leases()
    test_corrupt_lease_fail_closed()
    test_doctor_and_static_authority()
    test_frontend_status()
    print("ALL ADAPTIVE SHADOW CONTRACTS PASS")


if __name__ == "__main__":
    main()
