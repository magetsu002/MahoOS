#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_causal_status import enrich_status, render_enriched_status


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        security = Path(tmp)
        active = security / "incidents/active"
        active.mkdir(parents=True)
        incident = {
            "incident_id": "inc-package-alpha",
            "subject": {"type": "package", "id": "alpha"},
            "signals": [{
                "kind": "integrity-drift",
                "source": "pacman-mtree",
                "details": {"items": [{"class": "modified", "package": "alpha", "path": "/usr/bin/alpha"}]},
            }],
        }
        (active / "inc-package-alpha.json").write_text(json.dumps(incident), encoding="utf-8")
        (active / "inc-bad.json").write_text("{bad", encoding="utf-8")
        base = {
            "kind": "guardian-live-status",
            "errors": ["existing-error"],
            "world_state": {"guardian": {"severity": {"level": 1, "label": "notice"}, "trust": {"state": "UNKNOWN"}, "self_health": {"state": "HEALTHY"}}},
            "system": {},
            "boot": {},
            "recovery": {},
            "active_incidents": [],
            "containment": {"state": "none"},
            "evidence_freshness": {},
            "authorized_operation_evidence": [],
        }
        enriched = enrich_status(base, security)
        check("causal graph is exposed on canonical status", enriched["causality"]["kind"] == "guardian-causal-graph")
        check("proven package file relation survives status projection", enriched["causality"]["counts"]["proven"] == 1)
        check("malformed causal evidence is explicit", "causal_incident_malformed:inc-bad.json" in enriched["errors"])
        check("pre-existing errors are preserved", "existing-error" in enriched["errors"])
        rendered = render_enriched_status(enriched)
        check("plain status renders causal section", "Causal relationships" in rendered and "proven=1" in rendered)
    print("ALL GUARDIAN CAUSAL STATUS TESTS PASS")


if __name__ == "__main__":
    main()
