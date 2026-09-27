#!/usr/bin/env python3
"""Automation-safe CLI entry point for Maho System."""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from typing import Sequence
from maho_system_status import collect_system_model
from maho_system_tui import PAGES, diagnostic_state_label, interactive, render

ALIASES = {
    "status": "Overview", "overview": "Overview", "doctor": "Doctor",
    "guard": "Guardian", "guardian": "Guardian", "trust": "Trust",
    "update": "Updates", "updates": "Updates", "behavior": "Behavior",
    "recovery": "Recovery", "logs": "Logs / Evidence", "evidence": "Logs / Evidence",
}

def plain(model, page: str, *, doctor_all: bool = False) -> str:
    if page == "Overview":
        s = model.summary
        human = lambda value: str(value).replace("_", " ").title()
        return "\n".join((
            f"System health: {human(s.operational_health)}", f"Trust: {human(s.trust)}",
            f"Guardian: {human(s.guardian_health)}", f"Severity: {human(s.severity)}",
            f"Updates: {s.updates}", f"Recovery: {s.recovery}",
            f"Behavior: {s.behavior}", f"Attention: {human(s.attention)}",
        )) + "\n"
    if page == "Doctor":
        items = list(model.diagnostics) if doctor_all else [item for item in model.diagnostics if item.attention]
        if not items:
            return "No checks require review. Use `maho doctor --all` to inspect every diagnostic.\n"
        rows = [
            f"{diagnostic_state_label(item):<22} {item.subsystem:<10} {item.summary}: {item.reason}"
            for item in items
        ]
        if not doctor_all:
            rows.append("")
            rows.append("Showing checks that need review. Use `maho doctor --all` for full diagnostics.")
        return "\n".join(rows) + "\n"
    width = max(80, min(140, shutil.get_terminal_size((100, 30)).columns))
    return render(model, width=width, height=60, page=page, color=False).rstrip() + "\n"

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="maho", description="Maho System status, diagnostics, and terminal interface")
    p.add_argument("section", nargs="?", default="status", choices=tuple(ALIASES) + ("tui",))
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="emit stable structured status")
    mode.add_argument("--tui", action="store_true", help="open the interactive Maho System interface")
    p.add_argument("--evidence", action="store_true", help="include authoritative subsystem evidence in JSON")
    p.add_argument("--all", action="store_true", help="show all Doctor diagnostics, including healthy/provider detail")
    return p

def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    arg_parser = parser()
    args = arg_parser.parse_args(raw_argv)
    page = "Overview" if args.section == "tui" else ALIASES[args.section]
    if args.all and page != "Doctor":
        arg_parser.error("--all is only valid with `maho doctor`")
    model = collect_system_model()
    if args.json:
        payload = model.as_dict(include_evidence=args.evidence)
        payload["view"] = page
        json.dump(payload, sys.stdout, sort_keys=True, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0
    if (not raw_argv and sys.stdin.isatty() and sys.stdout.isatty()) or args.section == "tui" or args.tui:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("maho: interactive TUI requires a terminal; use plain output or --json", file=sys.stderr)
            return 2
        return interactive(model, page=page)
    sys.stdout.write(plain(model, page, doctor_all=args.all))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
