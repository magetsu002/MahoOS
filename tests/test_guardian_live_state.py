#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_evidence import EvidenceFreshness, ProviderHealth  # noqa: E402
from guardian_live_state import LivePaths, ProviderSpec, _provider_envelope  # noqa: E402
from guardian_provider_state import record_heartbeat  # noqa: E402

NOW = datetime(2026, 9, 15, 8, 30, tzinfo=timezone.utc)
SPEC = ProviderSpec("security.integrity", "security", 600, "monitor-v2/integrity.json")


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def paths(root: Path) -> LivePaths:
    security = root / "security"
    state = root / "state"
    update = root / "update"
    recovery = root / "recovery"
    runtime = root / "runtime"
    proc = root / "proc"
    for item in (security, state, update, recovery, runtime, proc / "sys/kernel/random"):
        item.mkdir(parents=True, exist_ok=True)
    (proc / "sys/kernel/random/boot_id").write_text("a" * 32 + "\n", encoding="utf-8")
    return LivePaths(security, state, update, recovery, runtime, proc)


def write_clean(p: LivePaths) -> Path:
    target = p.security_root / "monitor-v2/integrity.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"version": 1, "kind": "package-file-integrity", "result": "clean"}) + "\n", encoding="utf-8")
    return target


def heartbeat(p: LivePaths, at: datetime, *, success: bool = True, health: ProviderHealth = ProviderHealth.HEALTHY) -> None:
    record_heartbeat(
        p.security_root,
        provider_id="security.integrity",
        domain="security",
        source="maho-security-monitor",
        authority_boundary="read-only-observer",
        success=success,
        health=health,
        now=at,
        details={"result": "clean"},
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = paths(Path(tmp))
        target = write_clean(p)
        heartbeat(p, NOW - timedelta(seconds=30))
        current, schema_ok = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("unchanged clean result plus current heartbeat is usable", schema_ok and current.decision_usable(now=NOW))
        check("successful observation is separate from state change", current.data["last_successful_observation_at"] != current.data["last_state_change_at"])

        stale_time = NOW - timedelta(minutes=20)
        heartbeat(p, stale_time)
        stale, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("unchanged clean result plus stale heartbeat is stale", stale.freshness(now=NOW) is EvidenceFreshness.STALE)
        check("stale clean result cannot be decision usable", stale.decision_usable(now=NOW) is False)

        os.utime(target, (NOW.timestamp(), NOW.timestamp()))
        state_recent, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("recent state change cannot rescue stale observer heartbeat", state_recent.freshness(now=NOW) is EvidenceFreshness.STALE and state_recent.data["last_state_change_at"] is not None)

        heartbeat_path = p.security_root / "guardian/providers/security.integrity.json"
        heartbeat_path.write_text("{not-json\n", encoding="utf-8")
        malformed, schema_ok = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("malformed heartbeat fails closed", not schema_ok and malformed.health is ProviderHealth.FAILED and not malformed.decision_usable(now=NOW))

    with tempfile.TemporaryDirectory() as tmp:
        p = paths(Path(tmp))
        write_clean(p)
        missing, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("historical clean state without current observation is missing", missing.freshness(now=NOW) is EvidenceFreshness.MISSING and not missing.decision_usable(now=NOW))

        heartbeat(p, NOW - timedelta(minutes=20))
        old, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        heartbeat(p, NOW - timedelta(seconds=5))
        recovered, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("provider recovers from stale to current only after new successful observation", old.freshness(now=NOW) is EvidenceFreshness.STALE and recovered.freshness(now=NOW) is EvidenceFreshness.CURRENT)

        heartbeat_file = p.security_root / "guardian/providers/security.integrity.json"
        heartbeat_file.unlink()
        disappeared, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("required provider disappearance after healthy state becomes missing", disappeared.freshness(now=NOW) is EvidenceFreshness.MISSING)

    with tempfile.TemporaryDirectory() as tmp:
        p = paths(Path(tmp))
        write_clean(p)
        heartbeat(p, NOW - timedelta(seconds=5))
        state_file = p.security_root / "monitor-v2/integrity.json"
        state_file.write_text("[]\n", encoding="utf-8")
        malformed_state, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("fresh heartbeat cannot make malformed provider state healthy", malformed_state.health is ProviderHealth.FAILED and not malformed_state.decision_usable(now=NOW))

        state_file.unlink()
        missing_state, _ = _provider_envelope(p, SPEC, state_root=p.security_root, now=NOW)
        check("fresh heartbeat cannot make disappeared provider state healthy", missing_state.health is ProviderHealth.UNKNOWN and not missing_state.decision_usable(now=NOW))

    print("ALL GUARDIAN LIVE STATE TESTS PASS")


if __name__ == "__main__":
    main()
