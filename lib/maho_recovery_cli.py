#!/usr/bin/env python3
"""Read-only CLI surface for MahoOS recovery-generation discovery."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from maho_recovery_discovery import Probe, SystemProbe, discover_recovery_generations
from maho_recovery_generation import RecoveryGenerationReport, report_json


def load_policy(path: str | Path) -> Mapping[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("platform policy must be a JSON object")
    return raw


def discover_report(policy_path: str | Path, probe: Probe | None = None) -> RecoveryGenerationReport:
    return discover_recovery_generations(load_policy(policy_path), probe or SystemProbe())


def render_human(report: RecoveryGenerationReport, *, limit: int = 10) -> str:
    p = report.current_platform
    generations = report.generations
    eligible = sum(1 for item in generations if item.eligible)
    selected = next((item for item in generations if item.generation_id == report.selected_generation_id), None)
    lines = [
        "MahoOS recovery generations",
        "",
        f"root filesystem           {p.get('root_fstype') or 'unknown'} {p.get('root_fsroot') or ''}".rstrip(),
        f"home rollback scope       {p.get('home_scope') or 'unknown'}",
        f"Snapper root              {'available' if p.get('snapper_config_available') else 'unavailable'}",
        f"target primary kernel     {'available' if p.get('primary_kernel_present') else 'missing'}",
        f"target LTS kernel         {'available' if p.get('lts_kernel_present') else 'missing'}",
        f"Limine                    {'available' if p.get('limine_present') else 'missing'}",
        f"limine-snapper-sync       {'available' if p.get('limine_snapper_sync_present') else 'missing'}",
        f"discovered generations    {len(generations)}",
        f"eligible generations      {eligible}",
        f"selected generation       {selected.generation_id if selected else 'none'}",
        f"certified system restore  {'yes' if report.certified_system_restore_plannable else 'no'}",
        "native restore           disabled",
    ]
    if generations:
        lines.extend(("", "Candidates:"))
        for item in generations[: max(0, limit)]:
            state = "ELIGIBLE" if item.eligible else "REJECT"
            reason = "coherent" if item.eligible else ",".join(item.rejection_reasons[:4])
            lines.append(
                f"  {state:<8} snapshot={item.snapshot.snapshot_id:<5} "
                f"id={item.generation_id or 'unavailable'}  {reason}"
            )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-platform recovery-generations")
    parser.add_argument("--policy", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = discover_report(args.policy)
    print(report_json(report) if args.json else render_human(report), end="" if not args.json else "\n")


if __name__ == "__main__":
    main()
