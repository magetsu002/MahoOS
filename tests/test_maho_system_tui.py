#!/usr/bin/env python3
from __future__ import annotations

import io
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_behavior_preferences import defaults, load_preferences  # noqa: E402
from maho_system_status import DiagnosticRecord, build_system_model  # noqa: E402
from maho_system_tui import PAGES, diagnostic_state_label, interactive, render  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def fixture(preferences=None, *, active: bool = False):
    guardian = {
        "system": {"current_system_generation": None, "current_kernel_generation": None, "maho_runtime": {"verified": True}},
        "reliability": {"state": "healthy", "counts": {"healthy": 4, "degraded": 0, "unknown": 0}},
        "world_state": {"guardian": {
            "self_health": {"state": "HEALTHY", "missing_providers": [], "stale_providers": []},
            "severity": {"level": 1, "label": "minor"},
            "trust": {"state": "UNKNOWN", "reasons": ["generation authority unavailable", "Signed Boot proof missing"]},
        }},
        "active_incidents": [{"incident_id": "inc-fixture", "status": "active", "explanation": {"incident": "Low-confidence persistence drift"}}],
        "boot": {"boot_generation_id": None, "boot_authority_id": None, "signed_boot_authority": "UNKNOWN", "trust_reason": "durable Signed Boot postboot proof is missing"},
        "evidence_freshness": {
            "boot.authority": {"freshness": "missing", "health": "healthy"},
            "environment.power": {"freshness": "missing", "health": "unknown"},
            "environment.thermal": {"freshness": "missing", "health": "unknown"},
            "guardian.watch": {"freshness": "current", "health": "healthy"},
        },
        "recent_activity": [{"kind": "incident", "at": "2026-01-01T00:00:00Z", "id": "inc-fixture", "status": "active"}],
        "containment": {"state": "none"}, "runtime_recovery": {"state": "recovered"},
        "response": {"backend_state": "RECOVERED", "wheel_spinning": False},
    }
    posture = {"notifications": "quiet", "maintenance": "suspended"} if active else {}
    behavior = {
        "captured_at": "2026-01-01T00:01:00Z", "snapshot_id": "sit-fixture", "blocked": None,
        "active_executable_posture": posture,
        "situation": {"workload": {"gaming": active}, "power": {"severity_band": "NORMAL"}, "thermal": {"level": "normal"}},
    }
    return build_system_model(
        guardian=guardian,
        update={
            "status": "Maintenance queued", "transaction_id": "upd-20260101T000000Z-123456789abc",
            "authority_state": "PREPARED", "attention_required": False, "blockers": [],
            "normal_execution_certified": False, "normal_authority_state": "stale-or-invalid",
            "presentation_status": "Waiting for certification",
            "receipt": {"state": "PREPARED", "prepared_time": "2026-01-01T00:00:30Z", "package_changes": [{"name": "fzf", "from": "1", "to": "2"}]},
        },
        behavior=behavior,
        adaptive_doctor={"healthy": True, "lease_state": "ok", "maintenance_projection_state": "active" if active else "absent"},
        recovery={
            "current_generation_trust": "UNRESOLVED", "recovery_modes": ["RUNTIME"],
            "last_verified_runtime_recovery": {"valid": True, "campaign_id": "runtime-fixture", "reason": "verified"},
            "last_verified_recovery": None, "invalid_unified_history_records": 0,
        },
        preferences=preferences or defaults(),
    )


def main() -> None:
    model = fixture()
    for width, height in ((160, 50), (120, 35), (100, 30), (80, 24)):
        for page in PAGES:
            screen = render(model, width=width, height=height, page=page)
            check(
                f"{page} fits {width}x{height}",
                len(screen.splitlines()) == height
                and all(len(line) <= width for line in screen.splitlines())
                and "\x1b[" not in screen,
            )
    overview = render(model)
    check("overview keeps health, Guardian, runtime, and trust distinct", all(value in overview for value in ("Healthy", "Verified", "Unresolved")))
    check("overview translates known attention reasons", "Not established" in overview and "Awaiting certification" in overview and "UNKNOWN" not in overview)
    trust_page = render(model, page="Trust", height=35)
    check("Trust renders boot certification absence semantically", "Awaiting certification" in trust_page)
    check("Trust renders missing generation authority semantically", trust_page.count("Not established") >= 2)
    check("Update page renders PREPARED stale authority semantically", "Waiting for certification" in render(model, page="Updates", height=35))
    check("Recovery page explains unresolved generation authority", "Awaiting generation trust" in render(model, page="Recovery", height=35))
    check("Guardian response projection remains truthful and idle", "RECOVERED" in render(model, page="Guardian", height=35) and "Idle" in render(model, page="Guardian", height=35))
    optional = [item for item in model.diagnostics if item.id in {"provider.environment.power", "provider.environment.thermal"}]
    check("optional telemetry absence does not request attention", len(optional) == 2 and all(not item.attention and "Not available" in item.reason for item in optional))
    doctor = render(model, page="Doctor", height=40)
    check("Doctor translates known trust reasons", "Not established" in doctor and "Awaiting certification" in doctor and "UNKNOWN" not in doctor)
    ambiguous = DiagnosticRecord("fixture.ambiguous", "Fixture", "UNKNOWN", "Ambiguous evidence", "No exact reason is available.", (), "Inspect evidence.", False)
    check("genuinely ambiguous evidence remains Unknown", diagnostic_state_label(ambiguous) == "Unknown")
    check("Trust page refuses historical promotion", "Historical recovery proof" in render(model, page="Trust", height=35))
    check("Update page explains package state", "fzf" in render(model, page="Updates", height=35))
    active = render(fixture(active=True), page="Behavior", height=35)
    check("Behavior page shows real certified activity", "Gaming" in active and "Notifications" in active and "suspended" in active)
    behavior_page = render(model, page="Behavior", height=40)
    check("Behavior preferences are grouped for humans", "FOCUS" in behavior_page and "POWER" in behavior_page and "THERMALS" in behavior_page)
    check("Behavior exposes granular work preferences", "sustained builds" in behavior_page and "rendering/encoding" in behavior_page)
    check("Behavior explains the selected preference", "Selected:" in behavior_page)
    check("Recovery page preserves authority boundary", "inspection-only" in render(model, page="Recovery", height=35))
    recovery_page = render(model, page="Recovery", height=35)
    check("Recovery uses None yet for absent native history", "Last native" in recovery_page and "None yet" in recovery_page and "Unavailable" not in recovery_page)
    check("Evidence view is bounded structured data", "Raw structured evidence (bounded)" in render(model, page="Guardian", evidence=True, height=30))
    check("render is deterministic", render(model, page="Overview") == render(model, page="Overview"))

    output = io.StringIO()
    interactive(model, stdin=io.StringIO("right\nq\n"), stdout=output, width=80, height=24, color=False)
    check("keyboard navigation redraws without mutation", output.getvalue().count("Maho System") == 2)

    with tempfile.TemporaryDirectory(prefix="maho-system-tui-") as temporary:
        path = Path(temporary) / "behavior.json"
        def provider():
            return fixture(load_preferences(path))
        interactive(
            provider(), stdin=io.StringIO("enter\nq\n"), stdout=io.StringIO(),
            width=80, height=24, color=False, page="Behavior",
            preference_path=path, model_provider=provider,
        )
        check("Behavior Enter toggles only user preference state", load_preferences(path).enabled("focus.quiet_notifications") is False)
    print("ALL MAHO SYSTEM TUI TESTS PASS")


if __name__ == "__main__":
    main()
