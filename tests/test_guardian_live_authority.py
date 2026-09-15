#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from guardian_live_state import LivePaths, _update_authority  # noqa: E402
from maho_update_state import UpdateState, create_transaction, transition_transaction, write_transaction  # noqa: E402

NOW = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)
TXID = "upd-20260915T090000Z-abcdef123456"
SHA = "a" * 40


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def paths(root: Path) -> LivePaths:
    security = root / "security"; security.mkdir()
    state = root / "state"; state.mkdir()
    update = root / "update"; update.mkdir()
    recovery = root / "recovery"; recovery.mkdir()
    runtime = root / "runtime"; runtime.mkdir()
    proc = root / "proc"; proc.mkdir()
    return LivePaths(security, state, update, recovery, runtime, proc)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        p = paths(Path(tmp))
        tx = create_transaction(
            transaction_id=TXID,
            source_revision=SHA,
            packages=[{"name":"maho-os","installed_version":"1","candidate_version":"2","repository":"maho","download_size":1,"installed_size":1,"roles":["maho-runtime"]}],
            activation_requirements=["restart"],
            recovery_generation_id="g3-1234567890abcdef12345678",
            now=NOW,
        )
        tx = transition_transaction(tx, UpdateState.STAGED, evidence={"payloads":"complete"}, now=NOW + timedelta(minutes=1))
        tx = transition_transaction(tx, UpdateState.PREPARED, now=NOW + timedelta(minutes=2))
        tx = transition_transaction(tx, UpdateState.MAINTENANCE_READY, now=NOW + timedelta(minutes=3))
        tx = transition_transaction(tx, UpdateState.INSTALLING, now=NOW + timedelta(minutes=4))
        tx_dir = p.update_root / "transactions"; tx_dir.mkdir(parents=True)
        write_transaction(tx_dir / f"{TXID}.json", tx)
        (p.update_root / "current").write_text(TXID + "\n", encoding="utf-8")
        current, records, errors = _update_authority(p)
        check("authoritative update record is consumed", current is not None and not errors and bool(records))
        check("runtime deployment evidence is surfaced", any(row["kind"] == "maho-runtime-deployment" for row in records))
        check("existing authority is not promoted to suppression without bounded window", all(row["suppression_ready"] is False and row["bounded_window"] is False for row in records))
    print("ALL GUARDIAN LIVE AUTHORITY TESTS PASS")


if __name__ == "__main__":
    main()
