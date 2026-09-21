#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_live_state import LivePaths, live_status, render_status  # noqa: E402
from guardian_provider_state import record_heartbeat  # noqa: E402
from guardian_evidence import ProviderHealth  # noqa: E402

NOW = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def make_paths(root: Path) -> LivePaths:
    security = root / "security"
    state = root / "state"
    update = root / "update"
    recovery = root / "recovery"
    runtime = root / "runtime"
    proc = root / "proc"
    signed_boot = root / "signed-boot"
    for item in (security, state, update, recovery, runtime / "releases", proc / "sys/kernel/random", signed_boot):
        item.mkdir(parents=True, exist_ok=True)
    (proc / "sys/kernel/random/boot_id").write_text("a" * 32 + "\n", encoding="utf-8")
    return LivePaths(security, state, update, recovery, runtime, proc, signed_boot)


def seed_security(p: LivePaths, at: datetime) -> None:
    monitor = p.security_root / "monitor-v2"
    monitor.mkdir(parents=True, exist_ok=True)
    values = {
        "packages": {"result": "observed", "packages": 10},
        "persistence": {"result": "clean"},
        "runtime": {"result": "clean"},
        "privilege": {"result": "clean"},
        "network": {"result": "clean"},
        "integrity": {"result": "clean"},
    }
    for name, value in values.items():
        (monitor / f"{name}.json").write_text(json.dumps(value) + "\n", encoding="utf-8")
        record_heartbeat(
            p.security_root,
            provider_id=f"security.{name}",
            domain="system" if name == "packages" else "security",
            source="maho-security-monitor",
            authority_boundary="read-only-observer",
            success=True,
            health=ProviderHealth.HEALTHY,
            now=at,
            details={"result": value["result"]},
        )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = make_paths(Path(tmp))
        seed_security(p, NOW - timedelta(seconds=5))
        payload = live_status(p, now=NOW)
        check("live projection has canonical kind", payload["kind"] == "guardian-live-status")
        check("missing signed boot proof remains explicit UNKNOWN", payload["boot"]["signed_boot_authority"] == "UNKNOWN")
        check("Signed Boot provider health remains separate from trust", payload["boot"]["provider_health"] == "healthy")
        check("generation trust is not invented", payload["system"]["current_system_generation"] is None and payload["system"]["current_kernel_generation"] is None)
        check("status reports provider freshness", payload["evidence_freshness"]["security.integrity"]["freshness"] == "current")
        rendered = render_status(payload)
        check("plain status exposes trust and Guardian health", "Overall trust" in rendered and "Guardian" in rendered)
        check("plain status explains missing boot proof semantically", "Awaiting certification" in rendered)
        check("no automatic containment authority is invented", payload["containment"]["automatic_authority"] is False)
        check("no automatic runtime recovery authority is invented", payload["runtime_recovery"]["automatic_authority"] is False and payload["runtime_recovery"]["state"] == "none")
        check("plain status exposes live runtime recovery separately from generation trust", "Runtime recovery" in render_status(payload))

        incident_id = "inc-host-stale-demo"
        source_dir = p.security_root / "incidents" / "active"
        guardian_dir = p.security_root / "guardian" / "active"
        source_dir.mkdir(parents=True)
        guardian_dir.mkdir(parents=True)
        source = {
            "incident_id": incident_id,
            "signals": [{"kind": "persistence-drift", "source": "persistence-baseline"}],
        }
        assessment = {
            "incident_id": incident_id,
            "source_kind": "security-incident",
            "status": "active",
            "subject": {"type": "host", "id": "local"},
            "decision": {"severity": {"level": 1, "label": "minor", "reason": "fixture"}},
        }
        (source_dir / f"{incident_id}.json").write_text(json.dumps(source) + "\n", encoding="utf-8")
        (guardian_dir / f"{incident_id}.json").write_text(json.dumps(assessment) + "\n", encoding="utf-8")

        cleared = live_status(p, now=NOW)
        check("fresh cleared provider supersedes retained incident latch", not cleared["active_incidents"] and cleared["retained_incidents"][0]["canonical_state"] == "superseded")
        check("superseded retained L1 cannot set current severity", cleared["world_state"]["guardian"]["severity"]["level"] == 0)

        persistence = p.security_root / "monitor-v2/persistence.json"
        persistence.write_text(json.dumps({"result": "changed", "attention_result": "changed"}) + "\n", encoding="utf-8")
        current = live_status(p, now=NOW)
        check("fresh active provider condition keeps incident current", len(current["active_incidents"]) == 1 and not current["retained_incidents"])
        check("current L1 severity remains Guardian-visible", current["world_state"]["guardian"]["severity"]["level"] == 1)
    print("ALL GUARDIAN LIVE STATUS TESTS PASS")


if __name__ == "__main__":
    main()
