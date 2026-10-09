#!/usr/bin/env python3
"""Explicit cache installation from a separately reviewed five-minute plan."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from maho_update_campaign import _campaign_mutex, _source_revision
from maho_update_cache_layout import installation_plan, install_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    plan = subs.add_parser("plan")
    plan.add_argument("--filesystem-uuid", required=True)
    install = subs.add_parser("install")
    install.add_argument("--plan", type=Path, required=True)
    install.add_argument("--confirm", required=True)
    args = parser.parse_args()
    revision = _source_revision(ROOT)
    if args.action == "plan":
        result = installation_plan(revision, args.filesystem_uuid)
    else:
        with _campaign_mutex():
            result = install_cache(json.loads(args.plan.read_text()), confirmation=args.confirm,
                                   source_revision=revision)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
