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
from maho_tui import (
    box, bounded_lines, clip, colorize_line, columns, field_rows, paint,
    read_key, short_id,
)


PAGES = (
    "Overview", "Doctor", "Guardian", "Trust", "Updates", "Behavior",
    "Recovery", "Logs / Evidence",
)
NAV_SHORT = ("Overview", "Doctor", "Guardian", "Trust", "Updates", "Behavior", "Recovery", "Evidence")
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


def _row_identity(model: SystemModel, page: str, row: int) -> str | None:
    if page == "Doctor" and model.diagnostics:
        return model.diagnostics[min(max(row, 0), len(model.diagnostics) - 1)].id
    if page == "Behavior" and SPECS:
        return SPECS[min(max(row, 0), len(SPECS) - 1)].key
    if page == "Logs / Evidence" and model.events:
        event = model.events[min(max(row, 0), len(model.events) - 1)]
        return "|".join((event.source, event.at or "", event.reference or "", event.label))
    return None


def restore_selection(model: SystemModel, page: str, identity: str | None, previous: int) -> int:
    if identity is None:
        return min(max(previous, 0), max(0, _row_count(model, page) - 1))
    if page == "Doctor":
        ids = [item.id for item in model.diagnostics]
    elif page == "Behavior":
        ids = [spec.key for spec in SPECS]
    elif page == "Logs / Evidence":
        ids = ["|".join((event.source, event.at or "", event.reference or "", event.label)) for event in model.events]
    else:
        ids = []
    if identity in ids:
        return ids.index(identity)
    return min(max(previous, 0), max(0, len(ids) - 1))


def _obj(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> Sequence[Mapping[str, Any]]:
    return tuple(item for item in value if isinstance(item, Mapping)) if isinstance(value, list) else ()


def _status_rows(model: SystemModel, width: int) -> list[str]:
    s = model.summary
    runtime = _obj(_obj(model.guardian.get("system")).get("maho_runtime"))
    rows: list[str] = []
    for label, value in (
        ("System health", _human_state(s.operational_health)),
        ("Guardian", _human_state(s.guardian_health)),
        ("Runtime", "Verified" if runtime.get("verified") is True else "Unverified"),
        ("Trust", _human_state(s.trust)), ("Severity", _human_state(s.severity)),
        ("Updates", s.updates), ("Recovery", s.recovery),
        ("Behavior", s.behavior), ("Attention", s.attention),
    ):
        rows.extend(field_rows(label, value, width - 4))
    return rows


def _overview(model: SystemModel, width: int) -> list[str]:
    groups = attention_groups(model)
    attention_rows = []
    for group in groups[:4]:
        attention_rows.append(f"{group.state:<22} {group.title}")
        attention_rows.append(f"        {group.reason}")
    if not attention_rows:
        attention_rows = ["No user attention is currently requested."]
    if width >= 86:
        left = box("Status", _status_rows(model, (width - 2) // 2), (width - 2) // 2)
        right_width = width - 2 - (width - 2) // 2
        right = box("Attention", attention_rows, right_width)
        return columns(left, right, width)
    return box("Status", _status_rows(model, width), width) + [""] + box("Attention", attention_rows, width)


def _doctor_rows(model: SystemModel, selected: int, width: int, offset: int = 0) -> list[str]:
    if not model.diagnostics:
        return ["No diagnostic records are available."]
    capacity = 10 if width >= 90 else 7
    start, end, selected = viewport_bounds(len(model.diagnostics), selected, capacity, offset)
    rows = []
    for index, item in enumerate(model.diagnostics[start:end], start):
        cursor = ">" if index == selected else " "
        display_state = diagnostic_state_label(item)
        rows.append(f"{cursor} {display_state:<22} {item.subsystem:<10} {item.summary}")
    return rows

def _doctor(model: SystemModel, state: UIState, width: int) -> list[str]:
    if not model.diagnostics:
        return box("Doctor", ["No diagnostic records are available."], width)
    selected = min(max(state.row_index, 0), len(model.diagnostics) - 1)
    item = model.diagnostics[selected]
    rows = box("Doctor", _doctor_rows(model, selected, width, state.row_offset), width)
    if state.show_detail:
        display_state = diagnostic_state_label(item, detail=True)
        detail = [
            f"State      {display_state}", f"Reason     {item.reason}",
            f"Impact     {'User attention requested' if item.attention else 'No user action requested'}",
            f"Action     {item.recommended_action}",
        ]
        if state.show_evidence:
            detail.append("Evidence   " + ", ".join(item.evidence_refs))
        rows += [""] + box(item.summary, detail, width)
    else:
        rows += ["", "Press [Enter] for explanation or [E] for evidence references."]
    return rows


def _guardian(model: SystemModel, width: int) -> list[str]:
    guardian = _obj(_obj(model.guardian.get("world_state")).get("guardian"))
    severity = _obj(guardian.get("severity"))
    health = _obj(guardian.get("self_health"))
    trust = _obj(guardian.get("trust"))
    incidents = _list(model.guardian.get("active_incidents"))
    status = []
    response = _obj(model.guardian.get("response"))
    for label, value in (
        ("Operational state", model.summary.operational_health),
        ("Trust", model.summary.trust),
        ("Severity", f"L{severity.get('level', '?')} {severity.get('label', 'unknown')}"),
        ("Guardian health", _human_state(health.get("state", "UNKNOWN"))),
        ("Containment", str(_obj(model.guardian.get("containment")).get("state", "none"))),
        ("Recovery", str(_obj(model.guardian.get("runtime_recovery")).get("state", "none"))),
        ("Response", str(response.get("backend_state", "NONE"))),
        ("Recovery activity", "Active" if response.get("wheel_spinning") is True else "Idle"),
    ):
        status.extend(field_rows(label, value, width - 4))
    incident_rows = []
    for item in incidents[:6]:
        decision = _obj(item.get("decision"))
        explanation = _obj(item.get("explanation"))
        incident_rows.extend((
            f"{short_id(str(item.get('incident_id') or 'unknown'), 32)}  {item.get('status', 'unknown')}",
            f"  {explanation.get('incident') or decision.get('reason') or 'No explanation supplied'}",
        ))
    if not incident_rows:
        incident_rows = ["No active Guardian incidents."]
    reasoning = [str(reason) for reason in trust.get("reasons", [])[:5]] if isinstance(trust.get("reasons"), list) else []
    return box("Guardian status", status, width) + [""] + box("Incidents", incident_rows, width) + ([""] + box("Trust reasoning", reasoning, width) if reasoning else [])


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


def _trust(model: SystemModel, width: int) -> list[str]:
    system = _obj(model.guardian.get("system"))
    runtime = _obj(system.get("maho_runtime"))
    boot = _obj(model.guardian.get("boot"))
    world_trust = _obj(_obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust"))
    guardian_health = _obj(_obj(_obj(model.guardian.get("world_state")).get("guardian")).get("self_health")).get("state")
    rows = [
        f"{'Maho runtime':<22} {'Verified' if runtime.get('verified') is True else 'Unverified'}",
        f"{'System generation':<22} {system.get('current_system_generation') or 'Not established'}",
        f"{'Kernel generation':<22} {system.get('current_kernel_generation') or 'Not established'}",
        f"{'Boot trust':<22} {_boot_trust_display(boot)}",
        f"{'Guardian observation':<22} {_human_state(guardian_health)}",
        "",
        f"{'Overall trust':<22} {_human_state(world_trust.get('state')) if str(world_trust.get('state')).upper() != 'UNKNOWN' else 'Unresolved'}",
        "Historical recovery proof is shown on Recovery and never promotes current trust.",
    ]
    reasons = [str(value) for value in world_trust.get("reasons", [])] if isinstance(world_trust.get("reasons"), list) else []
    if reasons:
        rows += [""] + reasons[:5]
    return box("Trust chain", rows, width)


def _updates(model: SystemModel, width: int) -> list[str]:
    update = model.update
    receipt = _obj(update.get("receipt"))
    rows: list[str] = []
    receipt_state = str(receipt.get("state") or update.get("authority_state") or "Unknown")
    for label, value in (
        ("Current state", str(update.get("presentation_status") or update.get("status", "Unknown"))),
        ("Transaction state", receipt_state),
        ("Transaction", short_id(str(update.get("transaction_id")), 38) if update.get("transaction_id") else "None"),
        ("Execution authority", "Current" if update.get("normal_execution_certified") is True else "Waiting for certification"),
        ("Activation", "Required" if update.get("activation_pending") is True else "Not pending"),
    ):
        rows.extend(field_rows(label, value, width - 4))
    changes = receipt.get("package_changes") if isinstance(receipt.get("package_changes"), list) else []
    package_rows = [f"{row.get('name')}  {row.get('from')} → {row.get('to')}" for row in changes[:8] if isinstance(row, Mapping)]
    blockers = update.get("blockers") if isinstance(update.get("blockers"), list) else []
    return box("Update status", rows, width) + [""] + box("Package summary", package_rows or ["No package changes in the current receipt."], width) + ([""] + box("Blockers", [str(item) for item in blockers], width) if blockers else [])


def _behavior(model: SystemModel, state: UIState, width: int) -> list[str]:
    situation = _obj(model.behavior.get("situation"))
    workload = _obj(situation.get("workload"))
    power = _obj(situation.get("power"))
    thermal = _obj(situation.get("thermal"))
    contexts = []
    if workload.get("gaming") is True: contexts.append("Gaming")
    if workload.get("compile") is True: contexts.append("Compiling")
    if workload.get("rendering") is True: contexts.append("Rendering")
    if str(power.get("severity_band")) in {"LOW", "CONSERVING", "CRITICAL"}: contexts.append(f"Battery {power.get('severity_band')}")
    if str(thermal.get("level")) in {"hot", "critical"}: contexts.append(f"Thermal {str(thermal.get('level')).title()}")
    posture = _obj(model.behavior.get("active_executable_posture"))
    current = [f"Context             {', '.join(contexts) if contexts else 'Normal'}"]
    current.extend(f"{key.replace('_', ' ').title():<19} {value}" for key, value in sorted(posture.items()))
    if not posture:
        current.append("Temporary changes   None")
    current.append("Returns to normal automatically after the condition and cooldown clear.")
    prefs = []
    selected = min(max(state.row_index, 0), len(SPECS) - 1)
    capacity = 7 if width >= 90 else 5
    start, end, selected = viewport_bounds(len(SPECS), selected, capacity, state.row_offset)
    for index, spec in enumerate(SPECS[start:end], start):
        cursor = ">" if index == selected else " "
        mark = "ON " if model.preferences.enabled(spec.key) else "OFF"
        prefs.append(f"{cursor} [{mark}] {spec.group}: {spec.label}")
    selected_spec = SPECS[selected]
    prefs += [
        "",
        f"Selected: {selected_spec.description}",
        "",
        "These switches restrict already-certified convenience behavior only.",
        "Guardian, trust, recovery, and independent safety coordination cannot be disabled here.",
    ]
    return box("Current automatic behavior", current, width) + [""] + box("Preferences", prefs, width)


def _recovery(model: SystemModel, width: int) -> list[str]:
    recovery = model.recovery
    last_runtime = _obj(recovery.get("last_verified_runtime_recovery"))
    last_native = _obj(recovery.get("last_verified_recovery"))
    rows = []
    for label, value in (
        ("Readiness", model.summary.recovery),
        ("Recovery authority", _recovery_authority_display(model)),
        ("Available scope", ", ".join(map(str, recovery.get("recovery_modes", []))) or "No verified mode"),
        ("Last runtime", short_id(str(last_runtime.get("campaign_id")), 40) if last_runtime else "None yet"),
        ("Last native", short_id(str(last_native.get("campaign_id")), 40) if last_native else "None yet"),
        ("Invalid history", str(recovery.get("invalid_unified_history_records", 0))),
    ):
        rows.extend(field_rows(label, value, width - 4))
    guidance = [
        "This page is inspection-only in normal mode.",
        "Exact plan selection, consent, and execution stay in Guardian Recovery.",
        "Use `maho recovery` to enter the existing bounded recovery interface.",
    ]
    return box("Recovery readiness", rows, width) + [""] + box("Authority boundary", guidance, width)


def _logs(model: SystemModel, state: UIState, width: int) -> list[str]:
    if not model.events:
        return box("Recent events", ["No structured recent events are available."], width)
    selected = min(max(state.row_index, 0), len(model.events) - 1)
    start, end, selected = viewport_bounds(len(model.events), selected, 12, state.row_offset)
    rows = []
    for index, event in enumerate(model.events[start:end], start):
        cursor = ">" if index == selected else " "
        at = (event.at or "historical").replace("T", " ")[:19]
        rows.append(f"{cursor} {at:<19} {event.source:<9} {event.state:<10} {event.label}")
    if state.show_detail:
        event = model.events[selected]
        rows += ["", f"Reference: {event.reference or 'not supplied'}"]
    return box("Recent events", rows, width)


def _raw(model: SystemModel, page: str, width: int, offset: int = 0, capacity: int = 20) -> list[str]:
    value: Any = {
        "Guardian": model.guardian, "Trust": _obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust", {}),
        "Updates": model.update, "Behavior": model.behavior, "Recovery": model.recovery,
        "Logs / Evidence": model.as_dict(include_evidence=True),
    }.get(page, model.as_dict(include_evidence=True))
    encoded = json.dumps(value, indent=2, sort_keys=True, default=str).splitlines()
    # Reserve box borders plus room for above/below scroll markers so the
    # compositor never hides the navigation state.
    capacity = max(1, capacity - 4)
    start = min(max(offset, 0), max(0, len(encoded) - capacity))
    window = encoded[start:start + capacity]
    if start:
        window.insert(0, f"… {start} lines above")
    if start + capacity < len(encoded):
        window.append(f"… {len(encoded) - start - capacity} lines below")
    return box("Raw structured evidence", window, width)

def _help(width: int) -> list[str]:
    return box("Help", [
        "[Left/Right or Tab] Sections", "[Up/Down] Select rows", "[Enter] Inspect or toggle a Behavior preference",
        "[Esc] Close detail/evidence", "[D] Doctor", "[E] Evidence", "[L] Logs / Evidence", "[?] Help", "[Q] Quit",
        "", "This interface presents existing authority. It does not create trust, select recovery, or execute mutation.",
    ], width)


def _body(model: SystemModel, state: UIState, width: int, height: int = 24) -> list[str]:
    if state.show_help:
        return _help(width)
    page = PAGES[state.page_index]
    if state.show_evidence:
        return _raw(model, page, width, state.detail_offset, height)
    if page == "Overview": return _overview(model, width)
    if page == "Doctor": return _doctor(model, state, width)
    if page == "Guardian": return _guardian(model, width)
    if page == "Trust": return _trust(model, width)
    if page == "Updates": return _updates(model, width)
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
    if page == "Behavior":
        return "[↑↓] Preference  [Enter] Toggle  [E] Evidence  [R] Refresh  [←→/Tab] Sections  [Q] Quit"
    if page in {"Doctor", "Logs / Evidence"}:
        return "[↑↓] Select  [Enter] Inspect  [E] Evidence  [R] Refresh  [←→/Tab] Sections  [Q] Quit"
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
        lines = [colorize_line(line) for line in lines]
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


def _row_count(model: SystemModel, page: str) -> int:
    if page == "Doctor": return len(model.diagnostics)
    if page == "Behavior": return len(SPECS)
    if page == "Logs / Evidence": return len(model.events)
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
        identity = _row_identity(model, page_name, state.row_index)
        previous = state.row_index
        model = model_provider()
        state.row_index = restore_selection(model, page_name, identity, previous)
        count = _row_count(model, page_name)
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
            if state.show_evidence:
                if key in {"up", "k"}: state.detail_offset = max(0, state.detail_offset - 1)
                elif key in {"down", "j"}: state.detail_offset += 1
                elif key == "page-up": state.detail_offset = max(0, state.detail_offset - 10)
                elif key == "page-down": state.detail_offset += 10
                elif key == "home": state.detail_offset = 0
                continue
            page_name = PAGES[state.page_index]
            count = _row_count(model, page_name)
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
