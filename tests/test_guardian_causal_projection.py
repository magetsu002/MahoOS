#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_causal_projection import load_active_security_incidents, project_security_causality


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def package_incident() -> dict:
    return {
        "incident_id": "inc-package-alpha",
        "subject": {"type": "package", "id": "alpha"},
        "risk": "critical",
        "confidence": "confirmed",
        "signals": [
            {
                "kind": "integrity-drift",
                "source": "pacman-mtree",
                "details": {
                    "items": [{"class": "modified", "package": "alpha", "path": "/usr/bin/alpha"}],
                    "count": 1,
                },
            },
            {
                "kind": "runtime-executable",
                "source": "procfs",
                "details": {
                    "pids": [222],
                    "observations": [{"pid": 222, "exe": "/usr/bin/alpha (deleted)", "signals": ["deleted-executable"]}],
                },
            },
            {
                "kind": "network-exposure",
                "source": "procfs-network",
                "details": {
                    "listeners": [{"pid": 222, "exe": "/usr/bin/alpha", "address": "0.0.0.0:9443"}],
                    "count": 1,
                },
            },
        ],
    }


def host_incident() -> dict:
    return {
        "incident_id": "inc-host-local",
        "subject": {"type": "host", "id": "local"},
        "risk": "medium",
        "confidence": "medium",
        "signals": [{
            "kind": "persistence-drift",
            "source": "persistence-baseline",
            "details": {
                "added": [{"path": "/etc/systemd/system/alpha.service", "kind": "systemd-system"}],
                "changed": [],
                "removed": [],
            },
        }],
    }


def main() -> None:
    graph = project_security_causality((package_incident(), host_incident()))
    payload = graph.as_dict()
    edges = payload["edges"]
    by_relation = {edge["relation"]: edge for edge in edges}

    check("package metadata produces proven package to file ownership",
          by_relation["package-owns-file"]["strength"] == "proven")
    check("runtime executable without stable identity remains correlated",
          by_relation["file-matches-process-executable"]["strength"] == "correlated")
    check("raw PID listener association remains correlated",
          by_relation["process-associated-with-listener"]["strength"] == "correlated")
    check("persistence cause remains unknown",
          by_relation["subject-persistence-relationship"]["strength"] == "unknown")
    check("causal projection never invents a numeric score", "score" not in payload)

    process_edges = [edge for edge in edges if edge["target"].startswith("process:")]
    check("no process edge becomes proven without stable identity",
          all(edge["strength"] != "proven" for edge in process_edges))

    with tempfile.TemporaryDirectory() as tmp:
        security = Path(tmp)
        active = security / "incidents/active"
        active.mkdir(parents=True)
        (active / "inc-package-alpha.json").write_text(json.dumps(package_incident()), encoding="utf-8")
        (active / "inc-bad.json").write_text("{bad", encoding="utf-8")
        rows, errors = load_active_security_incidents(security)
        check("durable active incident loader keeps valid records", len(rows) == 1)
        check("malformed durable incident is explicit", errors == ("inc-bad.json",))

    print("ALL GUARDIAN CAUSAL PROJECTION TESTS PASS")


if __name__ == "__main__":
    main()
