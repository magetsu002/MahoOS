#!/usr/bin/env python3
"""Automation-safe CLI entry point for Maho System."""
from __future__ import annotations
import argparse
import json
import shutil
import sys
from typing import Sequence
from maho_system_status import collect_system_model
from maho_system_tui import PAGES, interactive, render

ALIASES = {
    "status": "Overview", "overview": "Overview", "doctor": "Doctor",
    "guard": "Guardian", "guardian": "Guardian", "trust": "Trust",
    "update": "Updates", "updates": "Updates", "behavior": "Behavior",
    "recovery": "Recovery", "logs": "Logs / Evidence", "evidence": "Logs / Evidence",
}

def plain(model, page: str) -> str:
    if page == "Overview":
        s = model.summary
        return "\n".join((
            f"System health: {s.operational_health}", f"Trust: {s.trust}",
            f"Guardian: {s.guardian_health}", f"Severity: {s.severity}",
            f"Updates: {s.updates}", f"Recovery: {s.recovery}",
            f"Behavior: {s.behavior}", f"Attention: {s.attention}",
        )) + "\n"
    if page == "Doctor":
        rows = [f"{item.state:<7} {item.subsystem:<10} {item.summary}: {item.reason}" for item in model.diagnostics]
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
    return p

def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser().parse_args(raw_argv)
    model = collect_system_model()
    page = "Overview" if args.section == "tui" else ALIASES[args.section]
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
    sys.stdout.write(plain(model, page))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
