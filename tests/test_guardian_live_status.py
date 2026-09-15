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
    for item in (security, state, update, recovery, runtime / "releases", proc / "sys/kernel/random"):
        item.mkdir(parents=True, exist_ok=True)
    (proc / "sys/kernel/random/boot_id").write_text("a" * 32 + "\n", encoding="utf-8")
    return LivePaths(security, state, update, recovery, runtime, proc)


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
        check("signed boot remains an explicit pending provider", payload["boot"]["signed_boot_authority"] == "pending-provider")
        check("generation trust is not invented", payload["system"]["current_system_generation"] is None and payload["system"]["current_kernel_generation"] is None)
        check("status reports provider freshness", payload["evidence_freshness"]["security.integrity"]["freshness"] == "current")
        check("plain status exposes trust and self-health", "Trust" in render_status(payload) and "Guardian self-health" in render_status(payload))
        check("no automatic containment authority is invented", payload["containment"]["automatic_authority"] is False)
    print("ALL GUARDIAN LIVE STATUS TESTS PASS")


if __name__ == "__main__":
    main()
