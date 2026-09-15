#!/usr/bin/env python3
"""Small CLI surface for the canonical live Guardian projection."""
from __future__ import annotations

import argparse
import json

from guardian_causal_status import enrich_status, render_enriched_status
from guardian_live_state import LivePaths, live_status


def main() -> int:
    parser = argparse.ArgumentParser(prog="guardian-live-status")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    paths = LivePaths.defaults()
    payload = enrich_status(live_status(paths), paths.security_root)
    if args.json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(render_enriched_status(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
