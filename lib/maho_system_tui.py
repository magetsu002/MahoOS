#!/usr/bin/env python3
"""Calm, read-only-by-default terminal interface for Maho System state."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Callable, Mapping, Sequence, TextIO

from maho_behavior_preferences import SPECS, write_preference
from maho_system_status import DiagnosticRecord, SystemModel, collect_system_model
from maho_tui import box, bounded_lines, clip, paint, read_key, short_id


PAGES = (
    "Overview", "Doctor", "Guardian", "Trust", "Updates", "Behavior",
    "Recovery", "Logs / Evidence",
)
NAV_SHORT = ("Overview", "Doctor", "Guardian", "Trust", "Updates", "Behavior", "Recovery", "Evidence")
EVIDENCE_FILTERS = ("All", "Guardian", "Updates", "Recovery", "Behavior", "Trust")
MIN_WIDTH = 60
MIN_HEIGHT = 18


@dataclass
class UIState:
    page_index: int = 0
    row_index: int = 0
    show_detail: bool = False
    show_evidence: bool = False
    show_help: bool = False
    row_offset: int = 0
    detail_offset: int = 0
    doctor_all: bool = False
    evidence_filter: int = 0


@dataclass(frozen=True)
class AttentionGroup:
    title: str
    state: str
    reason: str
    diagnostic_ids: tuple[str, ...]


def attention_groups(model: SystemModel) -> tuple[AttentionGroup, ...]:
    """Group presentation-level symptoms without altering source diagnostics."""
    pending = [item for item in model.diagnostics if item.attention]
    groups: list[AttentionGroup] = []
    trust_ids = {"trust.current-generation", "trust.signed-boot", "provider.boot.authority"}
    trust = [item for item in pending if item.id in trust_ids]
    if trust:
        groups.append(AttentionGroup(
            "Physical trust certification incomplete",
            "Untrusted" if any(item.state == "FAIL" for item in trust) else "Unresolved",
            "Boot and current-generation authority are not fully established.",
            tuple(item.id for item in trust),
        ))
        pending = [item for item in pending if item.id not in trust_ids]
    for item in pending:
        groups.append(AttentionGroup(
            item.summary, diagnostic_state_label(item), item.reason, (item.id,),
        ))
    return tuple(groups)


def viewport_bounds(count: int, selected: int, capacity: int, offset: int = 0) -> tuple[int, int, int]:
    """Return a stable window that always keeps the selected row reachable."""
    if count <= 0:
        return 0, 0, 0
    capacity = max(1, capacity)
    selected = min(max(selected, 0), count - 1)
    max_start = max(0, count - capacity)
    start = min(max(offset, 0), max_start)
    if selected < start:
        start = selected
    elif selected >= start + capacity:
        start = selected - capacity + 1
    start = min(max(start, 0), max_start)
    return start, min(count, start + capacity), selected


def _doctor_items(model: SystemModel, show_all: bool = False) -> list[DiagnosticRecord]:
    if show_all:
        return list(model.diagnostics)
    optional = {"provider.environment.power", "provider.environment.thermal"}
    return [
        item for item in model.diagnostics
        if item.attention or (item.state != "PASS" and item.id not in optional)
    ]


def _event_items(model: SystemModel, state: UIState | None = None) -> list[Any]:
    name = EVIDENCE_FILTERS[state.evidence_filter] if state else "All"
    if name == "All":
        return list(model.events)
    expected = "Update" if name == "Updates" else name
    return [event for event in model.events if event.source == expected]


def _row_identity(model: SystemModel, page: str, row: int, state: UIState | None = None) -> str | None:
    if page == "Doctor":
        rows = _doctor_items(model, bool(state and state.doctor_all))
        if rows:
            return rows[min(max(row, 0), len(rows) - 1)].id
    if page == "Updates":
        changes = _package_changes(model)
        if changes:
            item = changes[min(max(row, 0), len(changes) - 1)]
            return str(item.get("name") or row)
    if page == "Behavior" and SPECS:
        return SPECS[min(max(row, 0), len(SPECS) - 1)].key
    if page == "Logs / Evidence":
        events = _event_items(model, state)
        if events:
            event = events[min(max(row, 0), len(events) - 1)]
            return "|".join((event.source, event.at or "", event.reference or "", event.label))
    return None


def restore_selection(
    model: SystemModel, page: str, identity: str | None, previous: int, state: UIState | None = None,
) -> int:
    if page == "Doctor":
        ids = [item.id for item in _doctor_items(model, bool(state and state.doctor_all))]
    elif page == "Updates":
        ids = [str(item.get("name") or index) for index, item in enumerate(_package_changes(model))]
    elif page == "Behavior":
        ids = [spec.key for spec in SPECS]
    elif page == "Logs / Evidence":
        ids = ["|".join((event.source, event.at or "", event.reference or "", event.label)) for event in _event_items(model, state)]
    else:
        ids = []
    if identity is not None and identity in ids:
        return ids.index(identity)
    return min(max(previous, 0), max(0, len(ids) - 1))


def _obj(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> Sequence[Mapping[str, Any]]:
    return tuple(item for item in value if isinstance(item, Mapping)) if isinstance(value, list) else ()


def _system_guidance(state: str) -> str:
    return {
        "HEALTHY": "You can continue using this machine normally.",
        "DEGRADED": "The machine is usable, but one or more system guarantees need review.",
        "FAILED": "Normal use should pause until the failing system condition is resolved.",
        "UNKNOWN": "Maho does not have enough current evidence to judge normal operation.",
    }.get(str(state).upper(), "Review current system evidence.")


def _overview(model: SystemModel, width: int) -> list[str]:
    summary = model.summary
    trust_state = _human_state(summary.trust)
    guardian_state = _human_state(summary.guardian_health)
    trust_text = {
        "Verified": "Current boot and generation trust are established.",
        "Unresolved": "Physical boot/generation certification is incomplete.",
        "Untrusted": "Current system trust has been explicitly lost.",
    }.get(trust_state, "Current trust evidence is incomplete.")
    guardian_text = (
        "All required current observers are responding."
        if str(summary.guardian_health).upper() == "HEALTHY"
        else "Guardian judgment is incomplete; inspect Guardian for missing or stale providers."
    )
    receipt = _obj(model.update.get("receipt"))
    changes = receipt.get("package_changes") if isinstance(receipt.get("package_changes"), list) else []
    kernels = receipt.get("kernel_changes") if isinstance(receipt.get("kernel_changes"), list) else []
    activity = str(model.update.get("presentation_status") or model.update.get("status") or "Idle")
    if changes or kernels:
        activity += f" · {len(changes)} packages · {len(kernels)} kernels"
    if receipt.get("activation_time"):
        live_text = "Activation occurred; post-activation verification determines completion."
    else:
        live_text = "Activation has not occurred; the current live system remains active."
    groups = attention_groups(model)
    rows = [
        f"SYSTEM      {_human_state(summary.operational_health)}",
        _system_guidance(summary.operational_health),
        "",
        f"TRUST       {trust_state}",
        trust_text,
        "",
        f"GUARDIAN    {guardian_state} · {summary.severity}",
        guardian_text,
        "",
        f"ACTIVITY    {activity}",
        live_text,
        "",
        f"NEEDS ATTENTION    {len(groups)} root issue{'s' if len(groups) != 1 else ''}",
    ]
    if groups:
        rows.extend(f"• {group.title} — {group.state}" for group in groups[:4])
    else:
        rows.append("No user attention is currently requested.")
    return box("System overview", rows, width)


def _doctor_rows(model: SystemModel, state: UIState, width: int) -> list[str]:
    items = _doctor_items(model, state.doctor_all)
    if not items:
        return ["No checks require review. Press [A] to show all checks."]
    capacity = 10 if width >= 90 else 7
    start, end, selected = viewport_bounds(len(items), state.row_index, capacity, state.row_offset)
    rows = []
    for index, item in enumerate(items[start:end], start):
        cursor = ">" if index == selected else " "
        rows.append(f"{cursor} {diagnostic_state_label(item):<22} {item.subsystem:<14} {item.summary}")
    return rows


def _doctor(model: SystemModel, state: UIState, width: int) -> list[str]:
    items = _doctor_items(model, state.doctor_all)
    mode = "All checks" if state.doctor_all else "Attention"
    if not items:
        return box(f"Doctor · {mode}", ["No checks require review.", "Press [A] to show all checks."], width)
    selected = min(max(state.row_index, 0), len(items) - 1)
    item = items[selected]
    rows = box(f"Doctor · {mode}", _doctor_rows(model, state, width), width)
    if state.show_detail:
        detail = [
            f"State               {diagnostic_state_label(item, detail=True)}",
            f"What happened       {item.summary}",
            f"Why it matters      {item.reason}",
            f"Recommended action  {item.recommended_action}",
            f"Evidence            {', '.join(item.evidence_refs) or 'No exact reference supplied'}",
        ]
        rows += [""] + box("Selected check", detail, width)
    else:
        rows += ["", "[Enter] Explain selected check   [A] Attention/All"]
    return rows


def _stage_symbol(value: Any) -> str:
    state = str(value or "unknown").lower()
    if state in {"complete", "completed", "contained", "recovered", "verified", "prevented", "success"}:
        return "✓"
    if state in {"active", "running", "recovering", "verifying", "pending", "in-progress"}:
        return "●"
    if state in {"failed", "failure", "blocked"}:
        return "!"
    if state in {"none", "not-applicable", "inactive", "idle"}:
        return "○"
    return "?"


def _guardian(model: SystemModel, width: int) -> list[str]:
    world = _obj(_obj(model.guardian.get("world_state")).get("guardian"))
    severity = _obj(world.get("severity"))
    health = _obj(world.get("self_health"))
    incidents = _list(model.guardian.get("active_incidents"))
    response = _obj(model.guardian.get("response"))
    stages = _obj(response.get("stages"))
    prevention = _obj(model.guardian.get("prevention"))
    containment = _obj(model.guardian.get("containment"))
    runtime_recovery = _obj(model.guardian.get("runtime_recovery"))
    active = bool(incidents)
    if active:
        lifecycle = (
            _stage_symbol(_obj(stages.get("prevent")).get("state")),
            "✓",
            _stage_symbol(_obj(stages.get("contain")).get("state") or containment.get("state")),
            _stage_symbol(_obj(stages.get("recover")).get("state") or runtime_recovery.get("state")),
            _stage_symbol(_obj(stages.get("verify")).get("state")),
        )
    else:
        lifecycle = ("○", "○", "○", "○", "○")
    level = severity.get("level", "?")
    label = str(severity.get("label") or "unknown").title()
    rows = [
        f"Guardian    L{level} {label} · {_human_state(health.get('state'))}",
        "",
        "PREVENT      DETECT      CONTAIN      RECOVER      VERIFY",
        f"   {lifecycle[0]}            {lifecycle[1]}           {lifecycle[2]}            {lifecycle[3]}           {lifecycle[4]}",
        "",
    ]
    if active:
        incident = incidents[0]
        decision = _obj(incident.get("decision"))
        explanation = _obj(incident.get("explanation"))
        incident_text = explanation.get("incident") or decision.get("reason") or "Guardian incident is active."
        current_stage = next((
            name.title() for name in ("verify", "recover", "contain", "prevent")
            if str(_obj(stages.get(name)).get("state", "")).lower() in {"active", "running", "pending", "recovering", "verifying", "in-progress"}
        ), str(response.get("backend_state") or "Assessing").replace("_", " ").title())
        rows.extend([
            f"INCIDENT     {short_id(str(incident.get('incident_id') or 'unknown'), 34)}",
            str(incident_text),
            f"CURRENT      {current_stage}",
            f"RESPONSE     {_human_state(response.get('backend_state'))}",
            f"AUTHORITY    {'Automatic bounded response' if response.get('automatic_authority') is True else 'No automatic response authority'}",
        ])
    else:
        rows.extend([
            "IDLE         No active Guardian incident.",
            f"PREVENTION   {str(prevention.get('state') or 'no evidence').replace('-', ' ').title()}",
        ])
        if str(prevention.get("state", "")).lower() in {"inactive-or-no-evidence", "inactive", "none", ""}:
            rows.append("Production prevention enforcement is not active; the gated boundary is not implied.")
        rows.append(f"SELF HEALTH  {_human_state(health.get('state'))}")
        if response.get("receipt_id"):
            rows.append(f"RECENT       {_human_state(response.get('backend_state'))} · {short_id(str(response.get('receipt_id')), 30)}")
    operations = _list(model.guardian.get("authorized_operation_evidence"))
    if operations:
        latest = operations[0]
        rows += [
            "",
            f"AUTHORIZED   {str(latest.get('kind') or 'operation').replace('-', ' ').title()} · {_human_state(latest.get('state'))}",
            f"              {short_id(str(latest.get('operation_id') or 'unknown'), 42)}",
        ]
    return box("Guardian lifecycle", rows, width)


def _human_state(value: Any) -> str:
    raw = str(value or "UNKNOWN").upper()
    return {
        "HEALTHY": "Healthy", "VERIFIED": "Verified", "DEGRADED": "Degraded",
        "UNKNOWN": "Unknown", "UNTRUSTED": "Untrusted", "RECOVERING": "Recovering",
        "RECOVERED": "Recovered", "CONTAINED": "Contained",
    }.get(raw, raw.replace("_", " ").title())


def _boot_trust_display(boot: Mapping[str, Any]) -> str:
    raw = str(boot.get("signed_boot_authority") or "UNKNOWN").upper()
    reason = str(boot.get("trust_reason") or "").lower()
    if raw == "VERIFIED":
        return "Verified"
    if raw in {"UNTRUSTED", "REVOKED"}:
        return "Untrusted"
    if "postboot proof is missing" in reason or "signed boot" in reason and "missing" in reason:
        return "Awaiting certification"
    return "Unknown"


def _recovery_authority_display(model: SystemModel) -> str:
    current = str(model.recovery.get("current_generation_trust") or "UNRESOLVED").upper()
    system = _obj(model.guardian.get("system"))
    if current == "VERIFIED":
        return "Verified"
    if not system.get("current_system_generation") or not system.get("current_kernel_generation"):
        return "Awaiting generation trust"
    if current in {"UNTRUSTED", "REVOKED", "CONTAMINATED"}:
        return "Untrusted"
    return "Unresolved"


def diagnostic_state_label(item: DiagnosticRecord, *, detail: bool = False) -> str:
    """Translate an enum only when the diagnostic carries an exact reason."""
    if item.state != "UNKNOWN":
        return item.state
    if item.id in {"provider.environment.power", "provider.environment.thermal"} and not item.attention:
        return "Not available" if detail else "N/A"
    reason = item.reason.lower()
    if item.id == "trust.current-generation" and (
        "generation authority" in reason or "systemgeneration/kernelgeneration authority" in reason
    ):
        return "Not established"
    if item.id == "trust.signed-boot" and (
        "signed boot" in reason and ("missing" in reason or "unavailable" in reason)
    ):
        return "Awaiting certification"
    if item.id == "provider.boot.authority" and "freshness is missing" in reason:
        return "Awaiting certification"
    if item.id == "recovery.readiness" and "verified modes: none" in reason:
        return "None yet"
    return "Unknown"


def _boot_authority_display(model: SystemModel) -> str:
    boot = _obj(model.guardian.get("boot"))
    freshness = _obj(_obj(model.guardian.get("evidence_freshness")).get("boot.authority"))
    signed = _boot_trust_display(boot)
    fresh = str(freshness.get("freshness") or "unknown").lower()
    if signed == "Untrusted":
        return "Untrusted"
    if fresh == "stale":
        return "Stale"
    if signed == "Verified" and boot.get("boot_authority_id"):
        return "Verified"
    if fresh == "missing" or signed == "Awaiting certification":
        return "Awaiting certification"
    return "Unknown"


def _generation_link(model: SystemModel, key: str) -> str:
    system = _obj(model.guardian.get("system"))
    current = str(model.recovery.get("current_generation_trust") or "UNRESOLVED").upper()
    if current in {"UNTRUSTED", "REVOKED", "CONTAMINATED"}:
        return "Untrusted"
    if not system.get(key):
        return "Awaiting certification"
    if current == "VERIFIED":
        return "Verified"
    return "Unknown"


def _guardian_observation_display(model: SystemModel) -> str:
    health = _obj(_obj(_obj(model.guardian.get("world_state")).get("guardian")).get("self_health"))
    if health.get("stale_providers"):
        return "Stale"
    state = str(health.get("state") or "UNKNOWN").upper()
    if state == "HEALTHY":
        return "Verified"
    if state in {"FAILED", "UNTRUSTED"}:
        return "Untrusted"
    return "Unknown"


def _trust(model: SystemModel, width: int) -> list[str]:
    system = _obj(model.guardian.get("system"))
    runtime = _obj(system.get("maho_runtime"))
    boot = _obj(model.guardian.get("boot"))
    world_trust = _obj(_obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust"))
    overall = _human_state(world_trust.get("state"))
    if str(world_trust.get("state") or "UNKNOWN").upper() == "UNKNOWN":
        overall = "Unresolved"
    links = [
        ("Boot root", _boot_trust_display(boot)),
        ("Boot authority", _boot_authority_display(model)),
        ("SystemGeneration", _generation_link(model, "current_system_generation")),
        ("KernelGeneration", _generation_link(model, "current_kernel_generation")),
        ("Maho runtime", "Verified" if runtime.get("verified") is True else "Unknown"),
        ("Guardian observation", _guardian_observation_display(model)),
        ("Overall trust", overall),
    ]
    rows: list[str] = []
    broken = False
    for index, (name, state) in enumerate(links):
        rows.append(f"{name:<22} {state}")
        if index < len(links) - 1:
            if not broken and state != "Verified":
                rows.append("        ↓  TRUST BREAK — upstream authority is not established")
                broken = True
            else:
                rows.append("        ↓")
    rows += [
        "",
        "A running component is not automatically trusted.",
        "Verified downstream runtime evidence does not repair an upstream trust break.",
        "Historical recovery proof never promotes current trust.",
    ]
    return box("Trust chain", rows, width)


def _package_changes(model: SystemModel) -> list[Mapping[str, Any]]:
    receipt = _obj(model.update.get("receipt"))
    raw = receipt.get("package_changes")
    return [item for item in raw if isinstance(item, Mapping)] if isinstance(raw, list) else []


def _update_lifecycle(receipt: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    completed = [
        bool(receipt.get("discovered_time")),
        bool(receipt.get("staged_time")),
        bool(receipt.get("prepared_time")),
        bool(receipt.get("installation_time")),
        receipt.get("native_update_execution_certified") is True,
        bool(receipt.get("activation_time")),
        bool(receipt.get("verification_time")),
    ]
    current = next((index for index, done in enumerate(completed) if not done), None)
    labels = ("DISCOVER", "STAGE", "PREPARE", "CANDIDATE", "ADMISSION", "ACTIVATE", "VERIFY")
    result = []
    for index, label in enumerate(labels):
        symbol = "✓" if completed[index] else "●" if index == current else "○"
        result.append((label, symbol))
    return tuple(result)


def _updates(model: SystemModel, state: UIState, width: int) -> list[str]:
    update = model.update
    receipt = _obj(update.get("receipt"))
    changes = _package_changes(model)
    kernel_names = receipt.get("kernel_changes") if isinstance(receipt.get("kernel_changes"), list) else []
    lifecycle = _update_lifecycle(receipt)
    package_generation = short_id(str(receipt.get("package_generation_id")), 24) if receipt.get("package_generation_id") else "none"
    recovery_generation = short_id(str(receipt.get("recovery_generation")), 24) if receipt.get("recovery_generation") else "none"
    requirements = receipt.get("activation_requirements") if isinstance(receipt.get("activation_requirements"), list) else []
    reboot = "yes" if "explicit-reboot" in requirements else "not explicit"
    rows = [
        f"{len(changes)} packages · {len(kernel_names)} kernels",
        f"Generations   package {package_generation} · recovery {recovery_generation}",
        " → ".join(label for label, _ in lifecycle),
        "   ".join(f"{symbol:^{max(5, len(label))}}" for label, symbol in lifecycle),
        f"State         {str(update.get('presentation_status') or update.get('status') or 'Unknown')}",
        f"Authority     {'Certified' if receipt.get('native_update_execution_certified') is True else 'Waiting for certification'} · recovery {'prepared' if receipt.get('native_l3_certified') is True and receipt.get('recovery_generation') else 'not prepared'}",
        (
            "Current root  Activation occurred; verification determines completion."
            if receipt.get("activation_time")
            else "Current root  Still active and untouched by candidate activation."
        ),
        f"Activation    {'required' if receipt.get('activation_required') is True else 'not required'} · reboot {reboot}",
    ]
    blockers = update.get("blockers") if isinstance(update.get("blockers"), list) else []
    if blockers:
        rows.append(f"BLOCKERS      {len(blockers)} · {str(blockers[0])}")

    package_by_name = {str(item.get("name")): item for item in changes}
    rows.append("KERNEL CHANGES")
    if kernel_names:
        for name in kernel_names[:2]:
            item = package_by_name.get(str(name), {})
            rows.append(
                f"  {name}  {item.get('from', '?')} → {item.get('to', '?')}"
                if item else f"  {name}"
            )
        if len(kernel_names) > 2:
            rows.append(f"  … {len(kernel_names) - 2} more kernel changes")
    else:
        rows.append("  None")

    rows.append("PACKAGE CHANGES")
    if changes:
        capacity = 5 if width >= 90 else 3
        start, end, selected = viewport_bounds(len(changes), state.row_index, capacity, state.row_offset)
        for index, item in enumerate(changes[start:end], start):
            cursor = ">" if index == selected else " "
            rows.append(f"{cursor} {item.get('name')}  {item.get('from')} → {item.get('to')}")
        rows.append(f"  Showing {start + 1}-{end} of {len(changes)} · ↑↓/PgUp/PgDn")
    else:
        rows.append("  No package changes in the current receipt.")
    return box("Updates", rows, width)


def _behavior(model: SystemModel, state: UIState, width: int) -> list[str]:
    situation = _obj(model.behavior.get("situation"))
    workload = _obj(situation.get("workload"))
    power = _obj(situation.get("power"))
    thermal = _obj(situation.get("thermal"))
    maintenance = _obj(situation.get("maintenance"))
    network = _obj(situation.get("network"))
    contexts = []
    if workload.get("gaming") is True: contexts.append("Gaming")
    if workload.get("compile") is True: contexts.append("Compiling")
    if workload.get("rendering") is True: contexts.append("Rendering")
    if workload.get("interactive") is True: contexts.append("Focused interactive work")
    if str(power.get("severity_band") or "").upper() in {"LOW", "CONSERVING", "CRITICAL"}:
        contexts.append(f"Battery {power.get('severity_band')}")
    if str(thermal.get("level") or "").lower() in {"hot", "critical"}:
        contexts.append(f"Thermal {str(thermal.get('level')).title()}")
    situation_rows = [f"Situation       {', '.join(contexts) if contexts else 'Normal'}"]
    if power:
        source = "AC" if power.get("ac_online") is True else "Battery"
        percent = f" · {power.get('percentage')}%" if power.get("percentage") is not None else ""
        situation_rows.append(f"Power           {source}{percent}")
    if thermal and thermal.get("level"):
        temperature = thermal.get("maximum_millidegree_c")
        suffix = f" · {int(temperature) / 1000:.0f}°C max" if isinstance(temperature, (int, float)) else ""
        situation_rows.append(f"Thermal         {str(thermal.get('level')).title()}{suffix}")
    if maintenance.get("in_critical_section") is True:
        situation_rows.append("Maintenance     Critical section active")
    if network and network.get("connectivity") != "online":
        situation_rows.append(f"Network         {str(network.get('connectivity') or 'unknown').title()}")

    posture = _obj(model.behavior.get("active_executable_posture"))
    leases = _list(model.behavior.get("leases"))
    proposals = _list(model.behavior.get("proposals"))
    blocked = model.behavior.get("blocked")
    adaptation = []
    if posture:
        for key, value in sorted(posture.items()):
            adaptation.append(f"{key.replace('_', ' ').title():<18} {value}")
        reason = next((str(item.get("reason")) for item in proposals if item.get("reason")), None)
        adaptation.append(f"Why              {reason or 'A certified current situation requires this temporary posture.'}")
        adaptation.append(f"Lease             {'Active' if leases else 'No active lease record'}")
        expiries = [item.get("expires_at") or item.get("expiry_at") for item in leases]
        expiry = next((str(value) for value in expiries if value), None)
        if expiry:
            adaptation.append(f"Returns           {expiry}")
        else:
            adaptation.append("Returns           Automatically after the condition and cooldown clear.")
    else:
        adaptation = [
            "Temporary changes  None",
            "Why                No adaptation required.",
            "Lease              None",
        ]
    if blocked:
        blocked_reason = blocked.get("reason") if isinstance(blocked, Mapping) else blocked
        adaptation.append(f"Blocked proposal   {blocked_reason or 'Blocked by current certified constraints'}")

    prefs = []
    selected = min(max(state.row_index, 0), len(SPECS) - 1)
    capacity = 5 if width >= 90 else 3
    start, end, selected = viewport_bounds(len(SPECS), selected, capacity, state.row_offset)
    for index, spec in enumerate(SPECS[start:end], start):
        cursor = ">" if index == selected else " "
        mark = "ON " if model.preferences.enabled(spec.key) else "OFF"
        prefs.append(f"{cursor} [{mark}] {spec.group}: {spec.label}")
    selected_spec = SPECS[selected]
    prefs += [
        f"Selected: {selected_spec.description}",
        "Convenience only. Guardian/trust/recovery/safety cannot be disabled here.",
    ]
    rows = ["CURRENT SITUATION", *situation_rows, "CURRENT ADAPTATION", *adaptation, "PREFERENCES", *prefs]
    return box("Behavior", rows, width)


def _recovery(model: SystemModel, width: int) -> list[str]:
    recovery = model.recovery
    last_runtime = _obj(recovery.get("last_verified_runtime_recovery"))
    last_native = _obj(recovery.get("last_verified_recovery"))
    guardian_recovery = _obj(model.guardian.get("runtime_recovery"))
    modes = [str(mode).title() for mode in recovery.get("recovery_modes", [])] if isinstance(recovery.get("recovery_modes"), list) else []
    native_campaign = short_id(str(last_native.get("campaign_id")), 28) if last_native else "None yet"
    runtime_campaign = short_id(str(last_runtime.get("campaign_id")), 28) if last_runtime else "None yet"
    known_system = (
        short_id(str(last_native.get("system_generation_id")), 28)
        if last_native.get("system_generation_id")
        else short_id(str(last_runtime.get("system_generation_id")), 28)
        if last_runtime.get("system_generation_id")
        else "Not recorded"
    )
    rows = [
        f"CAPABILITY   {model.summary.recovery} · modes: {', '.join(modes) if modes else 'none'}",
        f"AUTHORITY    {_recovery_authority_display(model)} · generation trust {_human_state(recovery.get('current_generation_trust'))}",
        "             Historical recovery evidence never establishes current authority.",
        f"KNOWN-GOOD   System {known_system}",
        f"             Native {native_campaign} · Runtime {runtime_campaign}",
        f"CURRENT      {_human_state(guardian_recovery.get('state'))} · last native {native_campaign}",
        f"HISTORY      {recovery.get('unified_history_count', 0)} records · {recovery.get('invalid_unified_history_records', 0)} invalid",
        (
            "             Integrity requires review."
            if int(recovery.get("invalid_unified_history_records", 0) or 0)
            else "             No invalid/tampered unified record is reported."
        ),
        "BOUNDARY     Inspection only. Execution stays in Guardian Recovery.",
        "             This screen never creates authority or promotes history to trust.",
    ]
    return box("Recovery", rows, width)


def _event_detail(model: SystemModel, event: Any) -> tuple[str, tuple[str, ...], str | None]:
    reference = event.reference
    if event.source == "Guardian":
        refs = ("guardian.recent_activity",) + ((f"guardian.incident:{reference}",) if reference else ())
        return "Guardian recorded this structured incident/activity event.", refs, reference
    if event.source == "Update":
        refs = ("update.receipt",) + ((f"update.transaction:{reference}",) if reference else ())
        return "Maho Update recorded this transaction state from the authoritative receipt.", refs, reference
    if event.source == "Behavior":
        refs = ("behavior.current",) + ((f"behavior.snapshot:{reference}",) if reference else ())
        return "Behavior evaluated the current situation and recorded its certified convenience posture.", refs, reference
    if event.source == "Recovery":
        refs = ("recovery.status",) + ((f"recovery.campaign:{reference}",) if reference else ())
        return "Guardian Recovery retained this verified recovery history record.", refs, reference
    if event.source == "Trust":
        return (
            "Guardian produced the current trust judgment from live trust signals; historical recovery does not promote it.",
            ("guardian.world_state.guardian.trust", "guardian.world_state.guardian.trust.signals"),
            reference,
        )
    return "Structured Maho evidence event.", ((reference,) if reference else ()), reference


def _logs(model: SystemModel, state: UIState, width: int) -> list[str]:
    events = _event_items(model, state)
    filter_name = EVIDENCE_FILTERS[state.evidence_filter]
    if not events:
        return box(f"Evidence · {filter_name}", ["No structured events match this filter.", "[F] Change filter"], width)
    selected = min(max(state.row_index, 0), len(events) - 1)
    start, end, selected = viewport_bounds(len(events), selected, 9, state.row_offset)
    rows = [f"Filter: {filter_name} · {len(events)} event{'s' if len(events) != 1 else ''} · [F] change"]
    for index, event in enumerate(events[start:end], start):
        cursor = ">" if index == selected else " "
        at = (event.at or "historical").replace("T", " ")[:19]
        rows.append(f"{cursor} {at:<19} {event.source:<9} {event.state:<12} {event.label}")
    if state.show_detail:
        event = events[selected]
        explanation, refs, related_id = _event_detail(model, event)
        rows += [
            "",
            f"Explanation  {explanation}",
            f"Reference    {event.reference or 'not supplied'}",
            f"Related      {', '.join(refs) or 'none'}",
            f"ID           {related_id or 'not supplied'}",
            "Press [E] for the structured evidence behind this selected item.",
        ]
    else:
        rows += ["", "[Enter] Inspect selected event   [E] Structured evidence"]
    return box(f"Evidence browser · {filter_name}", rows, width)


def _selected_evidence_payload(model: SystemModel, state: UIState) -> Any:
    events = _event_items(model, state)
    if not events:
        return {"filter": EVIDENCE_FILTERS[state.evidence_filter], "events": []}
    selected = min(max(state.row_index, 0), len(events) - 1)
    event = events[selected]
    explanation, refs, related_id = _event_detail(model, event)
    metadata = {
        "source": event.source,
        "at": event.at,
        "label": event.label,
        "state": event.state,
        "reference": event.reference,
        "explanation": explanation,
        "related_evidence_refs": list(refs),
        "related_id": related_id,
    }
    if event.source == "Guardian":
        source = model.guardian
    elif event.source == "Update":
        source = model.update
    elif event.source == "Behavior":
        source = model.behavior
    elif event.source == "Recovery":
        source = model.recovery
    elif event.source == "Trust":
        source = _obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust", {})
    else:
        source = model.as_dict(include_evidence=True)
    return {"selected_event": metadata, "source_evidence": source}


def _raw(
    model: SystemModel, page: str, width: int, offset: int = 0, capacity: int = 20,
    state: UIState | None = None,
) -> list[str]:
    value: Any = {
        "Guardian": model.guardian,
        "Trust": _obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust", {}),
        "Updates": model.update,
        "Behavior": model.behavior,
        "Recovery": model.recovery,
        "Logs / Evidence": _selected_evidence_payload(model, state or UIState(page_index=PAGES.index("Logs / Evidence"))),
    }.get(page, model.as_dict(include_evidence=True))
    encoded = json.dumps(value, indent=2, sort_keys=True, default=str).splitlines()
    capacity = max(1, capacity - 4)
    start = min(max(offset, 0), max(0, len(encoded) - capacity))
    window = encoded[start:start + capacity]
    if start:
        window.insert(0, f"… {start} lines above")
    if start + capacity < len(encoded):
        window.append(f"… {len(encoded) - start - capacity} lines below")
    return box("Structured evidence", window, width)

def _help(width: int) -> list[str]:
    return box("Help", [
        "[Left/Right or Tab] Sections   [1-8] Direct section",
        "[Up/Down] Select   [PgUp/PgDn] Move viewport   [Home/End] First/last",
        "[Enter] Inspect or toggle a Behavior preference   [F] Evidence filter",
        "[R] Refresh now   [E] Structured evidence   [D] Doctor   [L] Evidence",
        "[Esc] Close detail/evidence   [?] Help   [Q] Quit",
        "",
        "This interface presents existing authority. It does not create trust, select recovery, or execute mutation.",
    ], width)


def _body(model: SystemModel, state: UIState, width: int, height: int = 24) -> list[str]:
    if state.show_help:
        return _help(width)
    page = PAGES[state.page_index]
    if state.show_evidence:
        return _raw(model, page, width, state.detail_offset, height, state)
    if page == "Overview": return _overview(model, width)
    if page == "Doctor": return _doctor(model, state, width)
    if page == "Guardian": return _guardian(model, width)
    if page == "Trust": return _trust(model, width)
    if page == "Updates": return _updates(model, state, width)
    if page == "Behavior": return _behavior(model, state, width)
    if page == "Recovery": return _recovery(model, width)
    return _logs(model, state, width)

def _resize(width: int, height: int) -> str:
    rows = ["Maho System", "", "Terminal too small", f"Current: {width}x{height}  Required: {MIN_WIDTH}x{MIN_HEIGHT}", "Resize to continue.", "", "[Q] Quit"]
    rows = [clip(row, max(1, width)).center(max(1, width)) for row in rows]
    top = max(0, (height - len(rows)) // 2)
    output = [""] * top + rows
    output = output[:height] + [""] * max(0, height - len(output))
    return "\n".join(output) + "\n"


def _footer(page: str, state: UIState) -> str:
    if state.show_evidence:
        return "[↑↓/PgUp/PgDn] Scroll evidence  [Esc/E] Back  [R] Refresh  [?] Help  [Q] Quit"
    if page == "Updates":
        return "[↑↓/PgUp/PgDn] Packages  [E] Evidence  [R] Refresh  [←→/Tab] Sections  [Q] Quit"
    if page == "Behavior":
        return "[↑↓] Preference  [Enter] Toggle  [E] Evidence  [R] Refresh  [←→/Tab] Sections  [Q] Quit"
    if page == "Doctor":
        return "[↑↓] Select  [Enter] Explain  [A] Attention/All  [E] Evidence  [R] Refresh  [←→/Tab] Sections  [Q] Quit"
    if page == "Logs / Evidence":
        return "[↑↓] Select  [Enter] Inspect  [F] Filter  [E] Evidence  [R] Refresh  [←→/Tab] Sections  [Q] Quit"
    return "[←→/Tab] Sections  [1-8] Jump  [E] Evidence  [R] Refresh  [D] Doctor  [L] Evidence  [?] Help  [Q] Quit"


def compose(
    model: SystemModel, state: UIState, *, width: int, height: int, color: bool,
    freshness_seconds: int | None = None,
) -> str:
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return _resize(width, height)
    width = min(width, 180)
    page = PAGES[state.page_index]
    title = "Maho System"
    human_status = f"{_human_state(model.summary.operational_health)} · Trust {_human_state(model.summary.trust)} · {model.summary.severity}"
    if freshness_seconds is not None:
        human_status += f" · Live · {max(0, freshness_seconds)}s ago"
    header = [clip(title + " " * max(1, width - len(title) - len(human_status)) + human_status, width), "─" * width]
    footer = ["─" * width, clip(_footer(page, state), width)]
    if width >= 110:
        sidebar_width = 21
        content_width = width - sidebar_width - 3
        body_height = height - 4
        body = bounded_lines(_body(model, state, content_width, body_height), body_height, content_width, "… more; scroll or enlarge the terminal")
        side = [("› " if name == page else "  ") + f"{i + 1} {name}" for i, name in enumerate(PAGES)]
        lines = header[:]
        for index, row in enumerate(body):
            left = side[index] if index < len(side) else ""
            lines.append(clip(left, sidebar_width).ljust(sidebar_width) + " │ " + clip(row, content_width))
    else:
        first = max(0, min(state.page_index - 1, len(PAGES) - 3))
        visible = range(first, min(len(PAGES), first + 3))
        nav = "  ".join(f"[{i + 1} {NAV_SHORT[i]}]" if i == state.page_index else f"{i + 1} {NAV_SHORT[i]}" for i in visible)
        body_height = height - 6
        body = bounded_lines(_body(model, state, width, body_height), body_height, width, "… more; scroll or enlarge the terminal")
        lines = header + [clip(nav, width), ""] + body
    while len(lines) < height - len(footer):
        lines.append("")
    lines = lines[: height - len(footer)] + footer
    if color:
        # Color only explicit UI tokens. Never infer semantics by matching prose.
        active = f"› {state.page_index + 1} {page}"
        lines = [line.replace(active, paint(active, "active", True)) for line in lines]
    return "\n".join(lines) + "\n"

def render(
    model: SystemModel, *, width: int = 100, height: int = 30,
    page: str = "Overview", row: int = 0, detail: bool = False,
    evidence: bool = False, color: bool = False,
) -> str:
    normalized = "Logs / Evidence" if page.lower() in {"logs", "evidence", "logs / evidence"} else page.title()
    if normalized not in PAGES:
        raise ValueError("unknown Maho System page")
    return compose(model, UIState(PAGES.index(normalized), row, detail, evidence), width=width, height=height, color=color)


def _row_count(model: SystemModel, page: str, state: UIState | None = None) -> int:
    if page == "Doctor": return len(_doctor_items(model, bool(state and state.doctor_all)))
    if page == "Updates": return len(_package_changes(model))
    if page == "Behavior": return len(SPECS)
    if page == "Logs / Evidence": return len(_event_items(model, state))
    return 1


def interactive(
    model: SystemModel, *, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout,
    width: int | None = None, height: int | None = None, color: bool | None = None,
    page: str = "Overview", preference_path: Path | None = None,
    model_provider: Callable[[], SystemModel] = collect_system_model,
) -> int:
    normalized = "Logs / Evidence" if page.lower() in {"logs", "evidence", "logs / evidence"} else page.title()
    state = UIState(page_index=PAGES.index(normalized))
    tty_output = bool(getattr(stdout, "isatty", lambda: False)())
    tty_input = bool(getattr(stdin, "isatty", lambda: False)())
    if color is None:
        color = tty_output
    dirty = True
    last_size = None
    last_refresh = time.monotonic()
    refresh_interval = 2.0

    def refresh() -> None:
        nonlocal model, last_refresh, dirty
        page_name = PAGES[state.page_index]
        identity = _row_identity(model, page_name, state.row_index, state)
        previous = state.row_index
        model = model_provider()
        state.row_index = restore_selection(model, page_name, identity, previous, state)
        count = _row_count(model, page_name, state)
        state.row_offset = viewport_bounds(count, state.row_index, 8, state.row_offset)[0]
        last_refresh = time.monotonic()
        dirty = True

    if tty_output:
        stdout.write("\033[?1049h\033[?25l")
        stdout.flush()
    try:
        while True:
            terminal = shutil.get_terminal_size((100, 30))
            screen_width = width or terminal.columns
            screen_height = height or terminal.lines
            size = (screen_width, screen_height)
            now = time.monotonic()
            if now - last_refresh >= refresh_interval:
                refresh()
                now = time.monotonic()
            if dirty or size != last_size:
                if tty_output:
                    stdout.write("\033[H")
                freshness = int(max(0.0, now - last_refresh)) if tty_output else None
                stdout.write(compose(model, state, width=screen_width, height=screen_height, color=bool(color), freshness_seconds=freshness))
                stdout.flush()
                dirty = False
                last_size = size
            key = read_key(stdin, timeout=.2 if tty_input else None)
            if key == "timeout":
                continue
            if key in {"q", "quit", "exit"}:
                return 0
            if screen_width < MIN_WIDTH or screen_height < MIN_HEIGHT:
                continue
            dirty = True
            if state.show_help:
                if key in {"?", "escape", "enter", "left"}:
                    state.show_help = False
                continue
            if key == "?":
                state.show_help = True
                continue
            if key == "r":
                refresh()
                continue
            if key == "escape":
                state.show_detail = False
                state.show_evidence = False
                state.detail_offset = 0
                continue
            if key in {str(i) for i in range(1, 9)}:
                state.page_index = int(key) - 1
                state.row_index = state.row_offset = state.detail_offset = 0
                state.show_detail = state.show_evidence = False
                continue
            if key in {"right", "tab"}:
                state.page_index = (state.page_index + 1) % len(PAGES)
                state.row_index = state.row_offset = state.detail_offset = 0
                state.show_detail = state.show_evidence = False
                continue
            if key in {"left", "shift-tab"}:
                state.page_index = (state.page_index - 1) % len(PAGES)
                state.row_index = state.row_offset = state.detail_offset = 0
                state.show_detail = state.show_evidence = False
                continue
            if key == "d":
                state.page_index = PAGES.index("Doctor"); state.row_index = state.row_offset = 0; continue
            if key == "l":
                state.page_index = PAGES.index("Logs / Evidence"); state.row_index = state.row_offset = 0; continue
            if key == "e":
                state.show_evidence = not state.show_evidence; state.detail_offset = 0; continue
            if key == "f" and PAGES[state.page_index] == "Logs / Evidence" and not state.show_evidence:
                state.evidence_filter = (state.evidence_filter + 1) % len(EVIDENCE_FILTERS)
                state.row_index = state.row_offset = state.detail_offset = 0
                state.show_detail = False
                continue
            if key == "a" and PAGES[state.page_index] == "Doctor":
                identity = _row_identity(model, "Doctor", state.row_index, state)
                state.doctor_all = not state.doctor_all
                state.row_index = restore_selection(model, "Doctor", identity, state.row_index, state)
                state.row_offset = 0
                continue
            if state.show_evidence:
                if key in {"up", "k"}: state.detail_offset = max(0, state.detail_offset - 1)
                elif key in {"down", "j"}: state.detail_offset += 1
                elif key == "page-up": state.detail_offset = max(0, state.detail_offset - 10)
                elif key == "page-down": state.detail_offset += 10
                elif key == "home": state.detail_offset = 0
                continue
            page_name = PAGES[state.page_index]
            count = _row_count(model, page_name, state)
            if key in {"up", "k"}: state.row_index = max(0, state.row_index - 1)
            elif key in {"down", "j"}: state.row_index = min(max(0, count - 1), state.row_index + 1)
            elif key == "page-up": state.row_index = max(0, state.row_index - 8)
            elif key == "page-down": state.row_index = min(max(0, count - 1), state.row_index + 8)
            elif key == "home": state.row_index = 0
            elif key == "end": state.row_index = max(0, count - 1)
            elif key in {"enter", " "}:
                if page_name == "Behavior" and SPECS:
                    spec = SPECS[min(state.row_index, len(SPECS) - 1)]
                    write_preference(spec.key, not model.preferences.enabled(spec.key), preference_path)
                    refresh()
                elif page_name in {"Doctor", "Logs / Evidence"}:
                    state.show_detail = not state.show_detail
            state.row_offset = viewport_bounds(count, state.row_index, 8, state.row_offset)[0]
    finally:
        if tty_output:
            stdout.write("\033[?25h\033[?1049l")
            stdout.flush()
    return 0
