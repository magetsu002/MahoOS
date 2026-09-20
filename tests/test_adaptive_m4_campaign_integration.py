#!/usr/bin/env python3
"""Prove the production M4B entry point consumes Adaptive before mutation."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import maho_update_campaign as campaign  # noqa: E402
from maho_adaptive_maintenance_state import MaintenanceVetoError  # noqa: E402
from maho_update_state import UpdateState  # noqa: E402


@contextmanager
def campaign_fixture(gate):
    names = (
        "_require_root", "_root", "_source_revision", "_machine_id",
        "_campaign_path", "_read_campaign", "_platform", "_repo_contract",
        "transaction_path", "read_transaction", "update_confirmation",
        "_generation_is_current", "SystemPreparationOps", "_runtime_identity",
        "read_l3_journal", "maintenance_gate_for_user", "publish_transaction",
        "NativeBtrfsOps",
    )
    original = {name: getattr(campaign, name) for name in names}
    calls = {"published": 0, "candidate": 0}
    journal = {
        "phase": "prepared", "source_revision": "a" * 40, "user": "fixture",
        "package_repo": {"config_path": "/etc/maho/pacman.conf", "config_sha256": "b" * 64, "repositories": ["core"]},
        "home_identity": {"device": 1}, "runtime_identity": {"uid": 1000},
        "l3_prepared": {"journal_path": "/fixture/l3.json"},
    }
    transaction = {
        "state": UpdateState.PREPARED.value,
        "package_generation": {"id": "pkg-fixture"},
    }

    class Host:
        def __init__(self, **_kwargs): pass
        def home_identity(self): return journal["home_identity"]

    class Btrfs:
        def __init__(self, *_args, **_kwargs): pass
        def create_candidate(self):
            calls["candidate"] += 1
            raise AssertionError("candidate mutation crossed Adaptive veto")

    try:
        campaign._require_root = lambda: None
        campaign._root = lambda: ROOT
        campaign._source_revision = lambda _root: journal["source_revision"]
        campaign._machine_id = lambda: "machine-fixture"
        campaign._campaign_path = lambda *_args: Path("/fixture/campaign.json")
        campaign._read_campaign = lambda _path: journal
        campaign._platform = lambda _root: {}
        campaign._repo_contract = lambda _platform: dict(journal["package_repo"])
        campaign.transaction_path = lambda *_args: Path("/fixture/transaction.json")
        campaign.read_transaction = lambda _path: transaction
        campaign.update_confirmation = lambda *_args: "exact-confirmation"
        campaign._generation_is_current = lambda _transaction: True
        campaign.SystemPreparationOps = Host
        campaign._runtime_identity = lambda _user: journal["runtime_identity"]
        campaign.read_l3_journal = lambda _path: {"phase": "prepared"}
        campaign.maintenance_gate_for_user = gate
        campaign.publish_transaction = lambda *_args: calls.__setitem__("published", calls["published"] + 1)
        campaign.NativeBtrfsOps = Btrfs
        yield calls
    finally:
        for name, value in original.items():
            setattr(campaign, name, value)


def expect_block(gate, fragment: str) -> None:
    with campaign_fixture(gate) as calls:
        try:
            campaign.execute_native_campaign("upd-fixture", "exact-confirmation")
        except RuntimeError as exc:
            assert fragment in str(exc), exc
        else:
            raise AssertionError("production M4B entry accepted unsafe Adaptive state")
        assert calls == {"published": 0, "candidate": 0}, calls


def main() -> None:
    expect_block(
        lambda _user: {
            "ok": False, "adaptive_maintenance": "suspended", "veto_active": True,
            "source_policy": "gaming.foreground",
        },
        "adaptive_maintenance_suspended:gaming.foreground",
    )
    print("PASS production M4B caller refuses a certified active veto before mutation")

    def invalid(_user):
        raise MaintenanceVetoError("adaptive maintenance veto is stale")

    expect_block(invalid, "adaptive maintenance execution state is unsafe")
    print("PASS production M4B caller fails closed on invalid or stale Adaptive state")
    print("ALL ADAPTIVE M4 CAMPAIGN INTEGRATION CONTRACTS PASS")


if __name__ == "__main__":
    main()
