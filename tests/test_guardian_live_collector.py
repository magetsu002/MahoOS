#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_evidence import ProviderHealth  # noqa: E402
from guardian_live_state import LivePaths, collect_provider_evidence  # noqa: E402
from guardian_journal_stream import CursorProbe, begin_stream, persist_stream  # noqa: E402
from guardian_provider_state import record_heartbeat  # noqa: E402

NOW = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def make_paths(root: Path) -> LivePaths:
    security = root / "security"; security.mkdir()
    state = root / "state"; state.mkdir()
    update = root / "update"; update.mkdir()
    recovery = root / "recovery"; recovery.mkdir()
    runtime = root / "runtime"; runtime.mkdir()
    proc = root / "proc"; (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text("a" * 32 + "\n", encoding="utf-8")
    return LivePaths(security, state, update, recovery, runtime, proc)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = make_paths(Path(tmp))
        stream = begin_stream(None, cursor=None, probe=CursorProbe.MISSING, boot_id="a" * 32, now=NOW)
        persist_stream(p.security_root, stream)
        record_heartbeat(p.security_root, provider_id="guardian.watch", domain="guardian", source="systemd-user-journal", authority_boundary="read-only-observer", success=True, health=ProviderHealth.HEALTHY, now=NOW)
        record_heartbeat(p.security_root, provider_id="guardian.service-events", domain="guardian", source="systemd-user-journal", authority_boundary="read-only-observer", success=False, health=ProviderHealth.UNKNOWN, errors=(stream.reason,), now=NOW)
        rows, errors, observed_stream = collect_provider_evidence(p, now=NOW + timedelta(seconds=1))
        by_id = {row.provider_id: row for row in rows}
        check("bootstrap stream is not reported continuous", observed_stream is not None and observed_stream.continuity.value == "bootstrap")
        check("bootstrap stream evidence is unknown", by_id["guardian.service-events"].health is ProviderHealth.UNKNOWN)
        check("missing provider records remain explicit", by_id["security.integrity"].observed_at is None)
        check("collector survives absent optional providers", not errors)
    print("ALL GUARDIAN LIVE COLLECTOR TESTS PASS")


if __name__ == "__main__":
    main()
