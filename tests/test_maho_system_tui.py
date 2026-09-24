#!/usr/bin/env python3
from __future__ import annotations

import io
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_behavior_preferences import SPECS, defaults, load_preferences  # noqa: E402
from maho_system_status import DiagnosticRecord, build_system_model  # noqa: E402
from maho_system_tui import PAGES, _update_lifecycle, attention_groups, diagnostic_state_label, interactive, render, restore_selection, viewport_bounds  # noqa: E402


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


def rebuild(model, *, guardian=None, update=None, behavior=None, recovery=None, collection_errors=()):
    return build_system_model(
        guardian=guardian if guardian is not None else model.guardian,
        update=update if update is not None else model.update,
        behavior=behavior if behavior is not None else model.behavior,
        adaptive_doctor=model.behavior_doctor,
        recovery=recovery if recovery is not None else model.recovery,
        preferences=model.preferences,
        collection_errors=collection_errors,
        login=model.login,
    )


def main() -> None:
    model = fixture()
    check("L0 renders as L0 Normal", fixture(severity_level=0).summary.severity == "L0 Normal")
    for width, height in ((160, 45), (120, 35), (100, 30), (80, 24)):
        for page in PAGES:
            screen = render(model, width=width, height=height, page=page)
            check(
                f"{page} fits {width}x{height}",
                len(screen.splitlines()) == height
                and all(len(line) <= width for line in screen.splitlines())
                and "\x1b[" not in screen,
            )
    too_small = render(model, width=59, height=17)
    check("too-small terminal screen remains available", "Terminal too small" in too_small and len(too_small.splitlines()) == 17)

    severity_labels = {0: "normal", 1: "minor", 2: "moderate", 3: "serious", 4: "critical"}
    for level, label in severity_labels.items():
        guardian = deepcopy(model.guardian)
        guardian["world_state"]["guardian"]["severity"] = {"level": level, "label": label}
        variant = rebuild(model, guardian=guardian)
        check(f"Guardian L{level} fixture renders exact severity", f"L{level} {label.title()}" in render(variant, page="Guardian", height=35))

    guardian_degraded = deepcopy(model.guardian)
    guardian_degraded["world_state"]["guardian"]["self_health"] = {
        "state": "DEGRADED", "missing_providers": [], "stale_providers": ["security.runtime"],
    }
    degraded_model = rebuild(model, guardian=guardian_degraded)
    check("Guardian degraded fixture remains degraded", "Degraded" in render(degraded_model, page="Guardian", height=35))
    check("stale Guardian provider is visible in trust chain", "Stale" in render(degraded_model, page="Trust", height=35))

    trusted_base = fixture(severity_level=0, incident=False)
    trusted_guardian = deepcopy(trusted_base.guardian)
    trusted_recovery = deepcopy(trusted_base.recovery)
    trusted_guardian["system"]["current_system_generation"] = "sys-gen-fixture"
    trusted_guardian["system"]["current_kernel_generation"] = "kernel-gen-fixture"
    trusted_guardian["boot"].update({
        "signed_boot_authority": "VERIFIED",
        "boot_authority_id": "boot-authority-fixture",
        "boot_generation_id": "boot-gen-fixture",
        "trust_reason": "durable Signed Boot postboot proof verified",
    })
    trusted_guardian["evidence_freshness"]["boot.authority"] = {"freshness": "current", "health": "healthy"}
    trusted_guardian["world_state"]["guardian"]["trust"] = {"state": "VERIFIED", "reasons": ["exact current authority verified"]}
    trusted_recovery["current_generation_trust"] = "VERIFIED"
    verified_model = rebuild(trusted_base, guardian=trusted_guardian, recovery=trusted_recovery)
    verified_trust = render(verified_model, page="Trust", height=35)
    check("verified trust chain has no upstream break", "Overall trust          Verified" in verified_trust and "TRUST BREAK" not in verified_trust)

    stale_guardian = deepcopy(trusted_guardian)
    stale_guardian["evidence_freshness"]["boot.authority"] = {"freshness": "stale", "health": "healthy"}
    stale_guardian["world_state"]["guardian"]["trust"] = {"state": "UNKNOWN", "reasons": ["boot authority evidence stale"]}
    stale_model = rebuild(trusted_base, guardian=stale_guardian, recovery=trusted_recovery)
    check("stale trust fixture cannot render verified chain", "Boot authority         Stale" in render(stale_model, page="Trust", height=35) and "TRUST BREAK" in render(stale_model, page="Trust", height=35))

    untrusted_guardian = deepcopy(trusted_guardian)
    untrusted_recovery = deepcopy(trusted_recovery)
    untrusted_guardian["boot"]["signed_boot_authority"] = "UNTRUSTED"
    untrusted_guardian["world_state"]["guardian"]["trust"] = {"state": "UNTRUSTED", "reasons": ["authority revoked"]}
    untrusted_recovery["current_generation_trust"] = "UNTRUSTED"
    untrusted_model = rebuild(trusted_base, guardian=untrusted_guardian, recovery=untrusted_recovery)
    check("untrusted trust fixture is explicit", "Untrusted" in render(untrusted_model, page="Trust", height=35))

    lifecycle_fields = (
        ("discovered_time", "2026-01-01T00:00:01Z"),
        ("staged_time", "2026-01-01T00:00:02Z"),
        ("prepared_time", "2026-01-01T00:00:03Z"),
        ("installation_time", "2026-01-01T00:00:04Z"),
        ("native_update_execution_certified", True),
        ("activation_time", "2026-01-01T00:00:05Z"),
        ("verification_time", "2026-01-01T00:00:06Z"),
    )
    lifecycle_labels = ("DISCOVER", "STAGE", "PREPARE", "CANDIDATE", "ADMISSION", "ACTIVATE", "VERIFY")
    for completed in range(8):
        receipt = {}
        for key, value in lifecycle_fields[:completed]:
            receipt[key] = value
        lifecycle = dict(_update_lifecycle(receipt))
        if completed < len(lifecycle_labels):
            check(f"update lifecycle stage {lifecycle_labels[completed]} becomes current", lifecycle[lifecycle_labels[completed]] == "●")
        check(f"update lifecycle preserves {completed} completed stages", sum(symbol == "✓" for symbol in lifecycle.values()) == completed)

    rejected_update = deepcopy(model.update)
    rejected_update["blockers"] = ["admission_rejected"]
    rejected_update["receipt"]["native_update_execution_certified"] = False
    check("Admission rejection remains visible", "BLOCKERS" in render(rebuild(model, update=rejected_update), page="Updates", height=35))
    pending_activation = deepcopy(model.update)
    pending_activation["receipt"]["installation_time"] = "2026-01-01T00:00:40Z"
    pending_activation["receipt"]["native_update_execution_certified"] = True
    pending_activation["presentation_status"] = "Installed pending activation"
    check("installed candidate waits at ACTIVATE", dict(_update_lifecycle(pending_activation["receipt"]))["ACTIVATE"] == "●")
    postboot = deepcopy(pending_activation)
    postboot["receipt"]["activation_time"] = "2026-01-01T00:00:50Z"
    check("postboot activation waits at VERIFY", dict(_update_lifecycle(postboot["receipt"]))["VERIFY"] == "●")
    healthy_update = deepcopy(postboot)
    healthy_update["receipt"]["verification_time"] = "2026-01-01T00:01:00Z"
    check("healthy update lifecycle completes every stage", all(symbol == "✓" for _, symbol in _update_lifecycle(healthy_update["receipt"])))

    for workload_name, label in (("compile", "Compiling"), ("rendering", "Rendering")):
        behavior = deepcopy(model.behavior)
        behavior["situation"]["workload"][workload_name] = True
        behavior["active_executable_posture"] = {"maintenance": "deferred"}
        behavior_page = render(rebuild(model, behavior=behavior), page="Behavior", height=35)
        check(f"Behavior {workload_name} fixture is contextual", label in behavior_page and "Current adaptation" not in behavior_page)
    battery_behavior = deepcopy(model.behavior)
    battery_behavior["situation"]["power"] = {"ac_online": False, "battery_present": True, "percentage": 14, "severity_band": "LOW"}
    check("Behavior battery conservation fixture is visible", "Battery LOW" in render(rebuild(model, behavior=battery_behavior), page="Behavior", height=35))
    thermal_behavior = deepcopy(model.behavior)
    thermal_behavior["situation"]["thermal"] = {"level": "hot", "maximum_millidegree_c": 88000}
    check("Behavior thermal adaptation fixture is visible", "Thermal Hot" in render(rebuild(model, behavior=thermal_behavior), page="Behavior", height=35))
    blocked_behavior = deepcopy(model.behavior)
    blocked_behavior["blocked"] = {"reason": "maintenance critical section"}
    check("Behavior blocked proposal is visible", "Blocked proposal" in render(rebuild(model, behavior=blocked_behavior), page="Behavior", height=35))

    idle_recovery_base = fixture(incident=False)
    no_recovery = deepcopy(idle_recovery_base.recovery)
    no_recovery.update({"recovery_modes": [], "last_verified_runtime_recovery": None, "last_verified_recovery": None})
    check("Recovery none-certified fixture is explicit", "Not certified" in render(rebuild(idle_recovery_base, recovery=no_recovery), page="Recovery", height=35))
    native_recovery = deepcopy(trusted_recovery)
    native_recovery["recovery_modes"] = ["NATIVE"]
    native_recovery["last_verified_recovery"] = {
        "valid": True, "campaign_id": "native-fixture",
        "system_generation_id": "sys-known-good", "kernel_generation_id": "kernel-known-good",
    }
    native_page = render(rebuild(trusted_base, guardian=trusted_guardian, recovery=native_recovery), page="Recovery", height=35)
    check("Recovery native generation fixture exposes known-good state", "Native certified" in native_page and "native-fixture" in native_page)
    recovering_guardian = deepcopy(model.guardian)
    recovering_guardian["runtime_recovery"]["state"] = "recovering"
    check("Recovery active fixture renders Recovering", "Recovering" in render(rebuild(model, guardian=recovering_guardian), page="Recovery", height=35))
    invalid_recovery = deepcopy(model.recovery)
    invalid_recovery["invalid_unified_history_records"] = 2
    invalid_recovery["unified_history_count"] = 3
    check("Recovery invalid history fixture requests review", "2 invalid" in render(rebuild(model, recovery=invalid_recovery), page="Recovery", height=35) and "Integrity requires review" in render(rebuild(model, recovery=invalid_recovery), page="Recovery", height=35))

    collector_failure = rebuild(model, collection_errors=("guardian collector failed",))
    check("collector failure never becomes healthy evidence", any(item.id.startswith("collection.") and item.state == "UNKNOWN" and item.attention for item in collector_failure.diagnostics))
    color_page = render(model, width=120, height=35, page="Overview", color=True)
    check("color rendering does not regex-color status prose", "\x1b[32mHealthy" not in color_page)

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
    check("Update page promotes kernels and activation requirements", "KERNEL CHANGES" in update_page and "linux-cachyos" in update_page and "reboot" in update_page)
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
    top_nav = "\n".join(render(model, page="Overview", width=80, height=24).splitlines()[:5])
    check(
        "all section tabs remain visible at 80x24",
        all(name in top_nav for name in ("Overview", "Doctor", "Guardian", "Trust", "Updates", "Behavior", "Recovery", "Evidence")),
    )
    check("active section uses visible tab treatment", "[Overview]" in top_nav)
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
