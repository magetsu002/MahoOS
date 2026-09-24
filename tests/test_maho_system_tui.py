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


def fixture(preferences=None, *, active: bool = False, severity_level: int = 1, incident: bool = True):
    guardian = {
        "system": {"current_system_generation": None, "current_kernel_generation": None, "maho_runtime": {"verified": True}},
        "reliability": {"state": "healthy", "counts": {"healthy": 4, "degraded": 0, "unknown": 0}},
        "world_state": {"guardian": {
            "self_health": {"state": "HEALTHY", "missing_providers": [], "stale_providers": []},
            "severity": {"level": severity_level, "label": "normal" if severity_level == 0 else "minor"},
            "trust": {"state": "UNKNOWN", "reasons": ["generation authority unavailable", "Signed Boot proof missing"]},
        }},
        "active_incidents": (
            [{"incident_id": "inc-fixture", "status": "active", "explanation": {"incident": "Low-confidence persistence drift"}}]
            if incident else []
        ),
        "prevention": {"state": "inactive-or-no-evidence", "recent": [], "prevented_count": 0},
        "boot": {"boot_generation_id": None, "boot_authority_id": None, "signed_boot_authority": "UNKNOWN", "trust_reason": "durable Signed Boot postboot proof is missing"},
        "evidence_freshness": {
            "boot.authority": {"freshness": "missing", "health": "healthy"},
            "environment.power": {"freshness": "missing", "health": "unknown"},
            "environment.thermal": {"freshness": "missing", "health": "unknown"},
            "guardian.watch": {"freshness": "current", "health": "healthy"},
        },
        "recent_activity": (
            [{"kind": "incident", "at": "2026-01-01T00:00:00Z", "id": "inc-fixture", "status": "active"}]
            if incident else []
        ),
        "containment": {"state": "contained" if incident else "none"},
        "runtime_recovery": {"state": "recovering" if incident else "recovered"},
        "response": {
            "backend_state": "RECOVERING" if incident else "RECOVERED",
            "wheel_spinning": incident,
            "automatic_authority": incident,
            "receipt_id": "recovery-receipt-fixture",
            "stages": {
                "prevent": {"state": "not-applicable"},
                "contain": {"state": "complete" if incident else "not-applicable"},
                "recover": {"state": "active" if incident else "complete"},
                "verify": {"state": "pending" if incident else "complete"},
            },
        },
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
            "receipt": {
                "state": "PREPARED",
                "discovered_time": "2026-01-01T00:00:10Z",
                "staged_time": "2026-01-01T00:00:20Z",
                "prepared_time": "2026-01-01T00:00:30Z",
                "installation_time": None,
                "activation_time": None,
                "verification_time": None,
                "native_update_execution_certified": False,
                "native_l3_certified": True,
                "package_generation_id": "pkg-fixture",
                "recovery_generation": "g3-fixture",
                "activation_required": True,
                "activation_requirements": ["explicit-reboot"],
                "kernel_changes": ["linux-cachyos"],
                "package_changes": [
                    {"name": "fzf", "from": "1", "to": "2"},
                    {"name": "linux-cachyos", "from": "7.1", "to": "7.2"},
                ],
            },
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
    check("recovery summary describes capability, not generic readiness", fixture(incident=False).summary.recovery == "Runtime certified")
    grouped = attention_groups(model)
    trust_group = next(group for group in grouped if group.title == "Physical trust certification incomplete")
    check("attention grouping preserves underlying diagnostics", set(trust_group.diagnostic_ids) == {"trust.current-generation", "trust.signed-boot", "provider.boot.authority"})
    overview = render(model)
    check("overview keeps system, Guardian, and trust distinct", all(value in overview for value in ("SYSTEM", "GUARDIAN", "TRUST", "Healthy", "Unresolved")))
    check("overview groups repeated trust symptoms", "Physical trust" in overview and "certification incomplete" in overview and "UNKNOWN" not in overview)
    trust_page = render(model, page="Trust", height=35)
    check("Trust renders boot certification absence semantically", "Awaiting certification" in trust_page)
    check("Trust renders missing generation authority semantically", trust_page.count("Awaiting certification") >= 3)
    check("Trust makes upstream break explicit", "TRUST BREAK" in trust_page and "Maho runtime" in trust_page and "Verified" in trust_page and "Overall trust" in trust_page and "Unresolved" in trust_page)
    update_page = render(model, page="Updates", height=35)
    check("Update page renders PREPARED stale authority semantically", "Waiting for certification" in update_page)
    check("Update page exposes lifecycle and untouched live root", all(value in update_page for value in ("DISCOVER", "STAGE", "PREPARE", "CANDIDATE", "ADMISSION", "ACTIVATE", "VERIFY", "Still active and untouched")))
    check("Update page promotes kernels and activation requirements", "Kernel changes" in update_page and "linux-cachyos" in update_page and "Reboot" in update_page)
    check("Update package viewport follows selected identity", "linux-cachyos" in render(model, page="Updates", row=1, height=35))
    check("Recovery page explains unresolved generation authority", "Awaiting generation trust" in render(model, page="Recovery", height=35))
    guardian_active = render(model, page="Guardian", height=35)
    check("Guardian renders response lifecycle", all(value in guardian_active for value in ("PREVENT", "DETECT", "CONTAIN", "RECOVER", "VERIFY", "CURRENT", "Recover")))
    guardian_idle = render(fixture(severity_level=0, incident=False), page="Guardian", height=35)
    check("Guardian idle view is calm L0 and does not invent prevention enforcement", "L0 Normal" in guardian_idle and "No active Guardian incident" in guardian_idle and "not active" in guardian_idle)
    optional = [item for item in model.diagnostics if item.id in {"provider.environment.power", "provider.environment.thermal"}]
    check("optional telemetry absence does not request attention", len(optional) == 2 and all(not item.attention and "Not available" in item.reason for item in optional))
    doctor = render(model, page="Doctor", height=40)
    check("Doctor defaults to attention-focused checks", "Doctor · Attention" in doctor and "PASS" not in doctor)
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
    recovery_page = render(model, page="Recovery", height=35)
    check("Recovery page preserves authority boundary", "BOUNDARY" in recovery_page and "Inspection only" in recovery_page and "Guardian Recovery" in recovery_page)
    check("Recovery uses None yet for absent native history", "last native None yet" in recovery_page and "Unavailable" not in recovery_page)
    narrow_behavior = render(model, page="Behavior", row=len(SPECS) - 1, width=80, height=24)
    check("Behavior keeps selected preference and safety boundary visible at 80x24", "Thermals:" in narrow_behavior and "cannot be disabled here" in narrow_behavior)
    narrow_recovery = render(model, page="Recovery", width=80, height=24)
    check("Recovery keeps authority, history, and boundary visible at 80x24", all(value in narrow_recovery for value in ("AUTHORITY", "HISTORY", "BOUNDARY", "Guardian Recovery")))
    evidence_page = render(model, page="Guardian", evidence=True, height=30)
    check("Evidence view exposes structured data and scrolling when needed", "Structured evidence" in evidence_page and "lines below" in evidence_page)
    selected_evidence = render(model, page="Logs / Evidence", evidence=True, height=35)
    check("Evidence E-view is scoped to the selected event", "selected_event" in selected_evidence and "source_evidence" in selected_evidence)
    browser_output = io.StringIO()
    interactive(model, stdin=io.StringIO("f\nenter\nq\n"), stdout=browser_output, width=100, height=30, color=False, page="Logs / Evidence")
    check("Evidence browser filters and explains selected events", "Evidence browser · Guardian" in browser_output.getvalue() and "Related" in browser_output.getvalue())
    raw_output = io.StringIO()
    interactive(model, stdin=io.StringIO("f\ne\nq\n"), stdout=raw_output, width=100, height=30, color=False, page="Logs / Evidence")
    check("Selected Guardian event resolves exact source evidence", "guardian.recent_activity" in raw_output.getvalue() and "source_evidence" in raw_output.getvalue())
    check("render is deterministic", render(model, page="Overview") == render(model, page="Overview"))
    for count, selected, capacity, offset in ((20, 0, 5, 10), (20, 19, 5, 0), (3, 2, 8, 0)):
        start, end, normalized = viewport_bounds(count, selected, capacity, offset)
        check(f"viewport keeps row {selected} reachable", start <= normalized < end)
    chosen = model.diagnostics[6].id
    reordered = replace(model, diagnostics=tuple(reversed(model.diagnostics)))
    restored = restore_selection(reordered, "Doctor", chosen, 6)
    doctor_view = [
        item for item in reordered.diagnostics
        if item.attention or (item.state != "PASS" and item.id not in {"provider.environment.power", "provider.environment.thermal"})
    ]
    check("refresh preserves diagnostic selection by stable identity", doctor_view[restored].id == chosen)

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
