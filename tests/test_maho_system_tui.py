#!/usr/bin/env python3
from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_behavior_preferences import SPECS, defaults, load_preferences  # noqa: E402
from maho_system_status import DiagnosticRecord, build_system_model  # noqa: E402
from maho_system_tui import PAGES, attention_groups, diagnostic_state_label, interactive, render, restore_selection, viewport_bounds  # noqa: E402


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def fixture(preferences=None, *, active: bool = False, severity_level: int = 1):
    guardian = {
        "system": {"current_system_generation": None, "current_kernel_generation": None, "maho_runtime": {"verified": True}},
        "reliability": {"state": "healthy", "counts": {"healthy": 4, "degraded": 0, "unknown": 0}},
        "world_state": {"guardian": {
            "self_health": {"state": "HEALTHY", "missing_providers": [], "stale_providers": []},
            "severity": {"level": severity_level, "label": "normal" if severity_level == 0 else "minor"},
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
    check("L0 renders as L0 Normal", fixture(severity_level=0).summary.severity == "L0 Normal")
    for width, height in ((160, 50), (120, 35), (100, 30), (80, 24)):
        for page in PAGES:
            screen = render(model, width=width, height=height, page=page)
            check(
                f"{page} fits {width}x{height}",
                len(screen.splitlines()) == height
                and all(len(line) <= width for line in screen.splitlines())
                and "\x1b[" not in screen,
            )
    check("Behavior idle summary renders Normal", model.summary.behavior == "Normal")
    check("recovery summary describes capability, not generic readiness", model.summary.recovery == "Runtime certified")
    grouped = attention_groups(model)
    trust_group = next(group for group in grouped if group.title == "Physical trust certification incomplete")
    check("attention grouping preserves underlying diagnostics", set(trust_group.diagnostic_ids) == {"trust.current-generation", "trust.signed-boot", "provider.boot.authority"})
    overview = render(model)
    check("overview keeps health, Guardian, runtime, and trust distinct", all(value in overview for value in ("Healthy", "Verified", "Unresolved")))
    check("overview groups repeated trust symptoms", "Physical trust" in overview and "certification incomplete" in overview and "UNKNOWN" not in overview)
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
    group_indexes = {group: next(i for i, spec in enumerate(SPECS) if spec.group == group) for group in {"Focus", "Power", "Thermals"}}
    check("Behavior preference groups remain reachable", all(group in render(model, page="Behavior", row=group_indexes[group], height=30) for group in group_indexes))
    check("Behavior exposes granular work preferences", "sustained builds" in behavior_page and "rendering/encoding" in behavior_page)
    check("Behavior explains the selected preference", "Selected:" in behavior_page)
    check("Recovery page preserves authority boundary", "inspection-only" in render(model, page="Recovery", height=35))
    recovery_page = render(model, page="Recovery", height=35)
    check("Recovery uses None yet for absent native history", "Last native" in recovery_page and "None yet" in recovery_page and "Unavailable" not in recovery_page)
    evidence_page = render(model, page="Guardian", evidence=True, height=30)
    check("Evidence view is scrollable structured data", "Raw structured evidence" in evidence_page and "lines below" in evidence_page)
    check("render is deterministic", render(model, page="Overview") == render(model, page="Overview"))
    for count, selected, capacity, offset in ((20, 0, 5, 10), (20, 19, 5, 0), (3, 2, 8, 0)):
        start, end, normalized = viewport_bounds(count, selected, capacity, offset)
        check(f"viewport keeps row {selected} reachable", start <= normalized < end)
    chosen = model.diagnostics[6].id
    reordered = replace(model, diagnostics=tuple(reversed(model.diagnostics)))
    restored = restore_selection(reordered, "Doctor", chosen, 6)
    check("refresh preserves diagnostic selection by stable identity", reordered.diagnostics[restored].id == chosen)

    output = io.StringIO()
    interactive(model, stdin=io.StringIO("right\nq\n"), stdout=output, width=80, height=24, color=False)
    check("keyboard navigation redraws without mutation", output.getvalue().count("Maho System") == 2)
    refresh_calls = [0]
    def refresh_provider():
        refresh_calls[0] += 1
        return model
    interactive(model, stdin=io.StringIO("r\nq\n"), stdout=io.StringIO(), width=80, height=24, color=False, model_provider=refresh_provider)
    check("R forces immediate model refresh", refresh_calls[0] == 1)

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
