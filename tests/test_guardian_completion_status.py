#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_completion_status import enrich_status, render_status


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = {
            "kind": "guardian-live-status",
            "errors": [],
            "world_state": {"guardian": {"severity": {"level": 0, "label": "normal"}, "trust": {"state": "UNKNOWN"}, "self_health": {"state": "HEALTHY"}}},
            "system": {}, "boot": {}, "recovery": {}, "active_incidents": [],
            "containment": {"state": "none"}, "authorized_operation_evidence": [],
            "evidence_freshness": {"security.integrity": {"freshness": "current", "health": "healthy"}},
        }
        enriched = enrich_status(base, Path(tmp))
        check("canonical status keeps causal projection", enriched["causality"]["kind"] == "guardian-causal-graph")
        check("canonical status exposes reliability projection", enriched["reliability"]["kind"] == "guardian-reliability")
        check("missing reliability providers remain unknown", enriched["reliability"]["state"] == "unknown")
        check("reliability freshness joins canonical freshness table", "reliability.memory" in enriched["evidence_freshness"])
        check("missing reliability evidence is not usable", enriched["evidence_freshness"]["reliability.memory"]["decision_usable"] is False)
        rendered = render_status(enriched)
        check("plain status contains one reliability section", "Reliability\n" in rendered)
    print("ALL GUARDIAN COMPLETION STATUS TESTS PASS")


if __name__ == "__main__":
    main()
