#!/usr/bin/env python3
"""Read-only CLI for bounded MahoOS L3 system-restore preflight."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from maho_recovery_discovery import Probe, SystemProbe, discover_recovery_generations
from maho_system_restore import SystemRestorePlan, plan_system_restore
from maho_system_restore_evidence import EvidenceProbe, SystemEvidenceProbe, collect_provider_evidence


def load_policy(path: str | Path) -> Mapping[str, Any]:
    raw = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(raw, Mapping):
        raise ValueError('platform policy must be a JSON object')
    return raw


def build_plan(
    policy_path: str | Path,
    generation_id: str,
    *,
    recovery_probe: Probe | None = None,
    provider_probe: EvidenceProbe | None = None,
) -> SystemRestorePlan:
    policy = load_policy(policy_path)
    report = discover_recovery_generations(policy, recovery_probe or SystemProbe())
    evidence = collect_provider_evidence(policy, provider_probe or SystemEvidenceProbe())
    return plan_system_restore(report, generation_id, policy, evidence)


def render_human(plan: SystemRestorePlan) -> str:
    lines = [
        'MahoOS L3 system restore preflight',
        '',
        f'generation               {plan.generation_id}',
        f'snapshot                 {plan.snapshot_id}',
        f'root source              {plan.root_snapshot_fsroot}',
        f'home scope               {plan.home_scope}',
        f'provider                 {plan.provider_package} {plan.provider_version}',
        f'campaign ready           {"yes" if plan.campaign_ready else "no"}',
        f'production enabled       {"yes" if plan.production_enabled else "no"}',
        'requires confirmation    yes',
        'automatic restore        no',
    ]
    if plan.blockers:
        lines.extend(('', 'Blockers:'))
        lines.extend(f'  - {item}' for item in plan.blockers)
    return '\n'.join(lines) + '\n'


def main() -> None:
    parser = argparse.ArgumentParser(prog='maho-system-restore-plan')
    parser.add_argument('--policy', required=True)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    plan = build_plan(args.policy, args.generation)
    if args.json:
        print(json.dumps(plan.as_dict(), sort_keys=True, separators=(',', ':')))
    else:
        print(render_human(plan), end='')


if __name__ == '__main__':
    main()
