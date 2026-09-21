#!/usr/bin/env python3
"""Calm, read-only-by-default terminal interface for Maho System state."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
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
MIN_WIDTH = 60
MIN_HEIGHT = 18


@dataclass
class UIState:
    page_index: int = 0
    row_index: int = 0
    show_detail: bool = False
    show_evidence: bool = False
    show_help: bool = False


def _obj(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> Sequence[Mapping[str, Any]]:
    return tuple(item for item in value if isinstance(item, Mapping)) if isinstance(value, list) else ()


def _status_rows(model: SystemModel, width: int) -> list[str]:
    s = model.summary
    rows: list[str] = []
    for label, value in (
        ("System health", s.operational_health), ("Trust", s.trust),
        ("Guardian", s.guardian_health), ("Severity", s.severity),
        ("Updates", s.updates), ("Recovery", s.recovery),
        ("Behavior", s.behavior), ("Attention", s.attention),
    ):
        rows.extend(field_rows(label, value, width - 4))
    return rows


def _overview(model: SystemModel, width: int) -> list[str]:
    attention = [item for item in model.diagnostics if item.attention]
    attention_rows = []
    for item in attention[:4]:
        attention_rows.append(f"{item.state:<7} {item.summary}")
        attention_rows.append(f"        {item.reason}")
    if not attention_rows:
        attention_rows = ["No user attention is currently requested."]
    if width >= 86:
        left = box("Status", _status_rows(model, (width - 2) // 2), (width - 2) // 2)
        right_width = width - 2 - (width - 2) // 2
        right = box("Attention", attention_rows, right_width)
        return columns(left, right, width)
    return box("Status", _status_rows(model, width), width) + [""] + box("Attention", attention_rows, width)


def _doctor_rows(model: SystemModel, selected: int, width: int) -> list[str]:
    if not model.diagnostics:
        return ["No diagnostic records are available."]
    selected = min(max(selected, 0), len(model.diagnostics) - 1)
    visible = 10 if width >= 90 else 7
    start = max(0, min(selected - visible // 2, len(model.diagnostics) - visible))
    rows = []
    for index, item in enumerate(model.diagnostics[start:start + visible], start):
        cursor = ">" if index == selected else " "
        rows.append(f"{cursor} {item.state:<7} {item.subsystem:<10} {item.summary}")
    return rows


def _doctor(model: SystemModel, state: UIState, width: int) -> list[str]:
    if not model.diagnostics:
        return box("Doctor", ["No diagnostic records are available."], width)
    selected = min(max(state.row_index, 0), len(model.diagnostics) - 1)
    item = model.diagnostics[selected]
    rows = box("Doctor", _doctor_rows(model, selected, width), width)
    if state.show_detail:
        detail = [
            f"State      {item.state}", f"Reason     {item.reason}",
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
    for label, value in (
        ("Operational state", model.summary.operational_health),
        ("Trust", model.summary.trust),
        ("Severity", f"L{severity.get('level', '?')} {severity.get('label', 'unknown')}"),
        ("Guardian health", str(health.get("state", "UNKNOWN"))),
        ("Containment", str(_obj(model.guardian.get("containment")).get("state", "none"))),
        ("Recovery", str(_obj(model.guardian.get("runtime_recovery")).get("state", "none"))),
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


def _trust_state(value: Any, *, missing: bool = False) -> str:
    if missing:
        return "MISSING"
    value = str(value or "UNKNOWN").upper()
    return {"UNKNOWN": "UNRESOLVED", "DEGRADED": "UNRESOLVED"}.get(value, value)


def _trust(model: SystemModel, width: int) -> list[str]:
    system = _obj(model.guardian.get("system"))
    runtime = _obj(system.get("maho_runtime"))
    boot = _obj(model.guardian.get("boot"))
    world_trust = _obj(_obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust"))
    rows = [
        f"{'Maho runtime':<22} {'VERIFIED' if runtime.get('verified') is True else 'UNRESOLVED'}",
        f"{'SystemGeneration':<22} {_trust_state(world_trust.get('state'), missing=not system.get('current_system_generation'))}",
        f"{'KernelGeneration':<22} {_trust_state(world_trust.get('state'), missing=not system.get('current_kernel_generation'))}",
        f"{'BootGeneration':<22} {_trust_state(None, missing=not boot.get('boot_generation_id'))}",
        f"{'BootAuthority':<22} {_trust_state(boot.get('signed_boot_authority'), missing=not boot.get('boot_authority_id'))}",
        f"{'Signed Boot evidence':<22} {_trust_state(boot.get('signed_boot_authority'))}",
        f"{'Guardian observation':<22} {_trust_state(_obj(_obj(_obj(model.guardian.get('world_state')).get('guardian')).get('self_health')).get('state'))}",
        "",
        f"{'Overall trust':<22} {model.summary.trust}",
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
    for label, value in (
        ("Current state", str(update.get("status", "Unknown"))),
        ("Transaction", short_id(str(update.get("transaction_id")), 38) if update.get("transaction_id") else "None"),
        ("Authority", str(update.get("authority_state", "UNKNOWN"))),
        ("Normal execution", "CERTIFIED" if update.get("normal_execution_certified") is True else str(update.get("normal_authority_state", "UNAVAILABLE")).upper()),
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
    last_group = None
    for index, spec in enumerate(SPECS):
        if spec.group != last_group:
            if prefs:
                prefs.append("")
            prefs.append(spec.group.upper())
            last_group = spec.group
        cursor = ">" if index == selected else " "
        mark = "ON " if model.preferences.enabled(spec.key) else "OFF"
        prefs.append(f"{cursor} [{mark}] {spec.label}")
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
        ("Current trust", str(recovery.get("current_generation_trust", "UNRESOLVED"))),
        ("Available scope", ", ".join(map(str, recovery.get("recovery_modes", []))) or "No verified mode"),
        ("Last runtime", short_id(str(last_runtime.get("campaign_id")), 40) if last_runtime else "Unavailable"),
        ("Last native", short_id(str(last_native.get("campaign_id")), 40) if last_native else "Unavailable"),
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
    visible = 12
    start = max(0, min(selected - visible // 2, len(model.events) - visible))
    rows = []
    for index, event in enumerate(model.events[start:start + visible], start):
        cursor = ">" if index == selected else " "
        at = (event.at or "historical").replace("T", " ")[:19]
        rows.append(f"{cursor} {at:<19} {event.source:<9} {event.state:<10} {event.label}")
    if state.show_detail:
        event = model.events[selected]
        rows += ["", f"Reference: {event.reference or 'not supplied'}"]
    return box("Recent events", rows, width)


def _raw(model: SystemModel, page: str, width: int) -> list[str]:
    value: Any = {
        "Guardian": model.guardian, "Trust": _obj(_obj(model.guardian.get("world_state")).get("guardian")).get("trust", {}),
        "Updates": model.update, "Behavior": model.behavior, "Recovery": model.recovery,
        "Logs / Evidence": model.as_dict(include_evidence=False),
    }.get(page, model.as_dict(include_evidence=False))
    encoded = json.dumps(value, indent=2, sort_keys=True, default=str).splitlines()
    return box("Raw structured evidence (bounded)", encoded[:80], width)


def _help(width: int) -> list[str]:
    return box("Help", [
        "[Left/Right or Tab] Sections", "[Up/Down] Select rows", "[Enter] Inspect or toggle a Behavior preference",
        "[Esc] Close detail/evidence", "[D] Doctor", "[E] Evidence", "[L] Logs / Evidence", "[?] Help", "[Q] Quit",
        "", "This interface presents existing authority. It does not create trust, select recovery, or execute mutation.",
    ], width)


def _body(model: SystemModel, state: UIState, width: int) -> list[str]:
    if state.show_help:
        return _help(width)
    page = PAGES[state.page_index]
    if state.show_evidence:
        return _raw(model, page, width)
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


def compose(model: SystemModel, state: UIState, *, width: int, height: int, color: bool) -> str:
    if width < MIN_WIDTH or height < MIN_HEIGHT:
        return _resize(width, height)
    width = min(width, 180)
    page = PAGES[state.page_index]
    title = "Maho System"
    status = f"Health {model.summary.operational_health} | Trust {model.summary.trust}"
    header = [clip(title + " " * max(1, width - len(title) - len(status)) + status, width), "─" * width]
    footer_text = "[←→/Tab] Sections  [↑↓] Rows  [Enter] Inspect  [D] Doctor  [E] Evidence  [L] Logs  [?] Help  [Q] Quit"
    footer = ["─" * width, clip(footer_text, width)]
    if width >= 110:
        sidebar_width = 21
        content_width = width - sidebar_width - 3
        body = bounded_lines(_body(model, state, content_width), height - 4, content_width, "… more; open the dedicated page or enlarge the terminal")
        side = [("› " if name == page else "  ") + name for name in PAGES]
        lines = header[:]
        for index, row in enumerate(body):
            left = side[index] if index < len(side) else ""
            lines.append(clip(left, sidebar_width).ljust(sidebar_width) + " │ " + clip(row, content_width))
    else:
        nav = "  ".join(f"[{name}]" if name == page else name for name in PAGES)
        body_height = height - 6
        body = bounded_lines(_body(model, state, width), body_height, width, "… more; use the dedicated page")
        lines = header + [clip(nav, width), ""] + body
    while len(lines) < height - len(footer):
        lines.append("")
    lines = lines[: height - len(footer)] + footer
    if color:
        lines = [colorize_line(line) for line in lines]
        active = f"› {page}"
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
    normalized = "Logs / Evidence" if page.lower() == "logs" else page.title()
    state = UIState(page_index=PAGES.index(normalized))
    if color is None:
        color = bool(getattr(stdout, "isatty", lambda: False)())
    dynamic = width is None or height is None
    dirty = True
    last_size = None
    while True:
        terminal = shutil.get_terminal_size((100, 30))
        screen_width = width or terminal.columns
        screen_height = height or terminal.lines
        size = (screen_width, screen_height)
        if dirty or size != last_size:
            stdout.write("\033[2J\033[H")
            stdout.write(compose(model, state, width=screen_width, height=screen_height, color=bool(color)))
            stdout.flush()
            dirty = False
            last_size = size
        key = read_key(stdin, timeout=.2 if dynamic else None)
        if key == "timeout": continue
        if key in {"q", "quit", "exit"}: return 0
        if screen_width < MIN_WIDTH or screen_height < MIN_HEIGHT: continue
        dirty = True
        if state.show_help:
            if key in {"?", "escape", "enter", "left"}: state.show_help = False
            continue
        if key == "?": state.show_help = True; continue
        if key == "escape": state.show_detail = False; state.show_evidence = False; continue
        if key in {"right", "tab"}:
            state.page_index = (state.page_index + 1) % len(PAGES); state.row_index = 0; state.show_detail = False; state.show_evidence = False; continue
        if key in {"left", "shift-tab"}:
            state.page_index = (state.page_index - 1) % len(PAGES); state.row_index = 0; state.show_detail = False; state.show_evidence = False; continue
        if key == "d": state.page_index = PAGES.index("Doctor"); state.row_index = 0; continue
        if key == "l": state.page_index = PAGES.index("Logs / Evidence"); state.row_index = 0; continue
        if key == "e": state.show_evidence = not state.show_evidence; continue
        page_name = PAGES[state.page_index]
        count = _row_count(model, page_name)
        if key in {"up", "k"}: state.row_index = max(0, state.row_index - 1); continue
        if key in {"down", "j"}: state.row_index = min(max(0, count - 1), state.row_index + 1); continue
        if key in {"enter", " "}:
            if page_name == "Behavior" and SPECS:
                spec = SPECS[min(state.row_index, len(SPECS) - 1)]
                write_preference(spec.key, not model.preferences.enabled(spec.key), preference_path)
                model = model_provider()
            elif page_name in {"Doctor", "Logs / Evidence"}:
                state.show_detail = not state.show_detail
    return 0
