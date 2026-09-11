#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_system_restore_journal import read_journal  # noqa: E402
from maho_system_restore_preparation import (  # noqa: E402
    PreparationBlocked,
    preparation_blockers,
    prepare_restore_transaction,
)

TX = "l3-20260911T120000Z-deadbeef"
MID = "0123456789abcdef0123456789abcdef"
REV = "a" * 40
TARGET_UUID = "target-snapshot-uuid"
BACKUP_UUID = "backup-snapshot-uuid"
ROOT_FS = "11111111-2222-3333-4444-555555555555"
HOME_FS = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
HOME_UUID = "home-subvolume-uuid"
KHASH = "1" * 64
IHASH = "2" * 64


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def plan(**changes) -> dict:
    base = {
        "ready": True,
        "restore_authorized": False,
        "generation_id": "g3-0123456789abcdef01234567",
        "snapshot_id": 349,
        "provider_command": "/usr/bin/limine-snapper-restore",
        "provider_package": "limine-snapper-sync",
        "provider_version": "1.31.0-1",
        "root_filesystem_uuid": ROOT_FS,
        "expected_kernel_package": "linux-cachyos",
        "expected_kernel_version": "7.1.8-1-cachyos",
        "expected_kernel_sha256": KHASH,
        "expected_initramfs_sha256": IHASH,
    }
    base.update(changes)
    return base

def provider(**changes) -> dict:
    base = {
        "path": "/usr/bin/limine-snapper-restore",
        "package": "limine-snapper-sync",
        "version": "1.31.0-1",
        "uid": 0,
        "mode": 0o755,
        "regular_file": True,
        "package_owns_command": True,
        "package_files_ok": True,
    }
    base.update(changes)
    return base


def home(**changes) -> dict:
    base = {
        "filesystem_uuid": HOME_FS,
        "fsroot": "/@home",
        "subvolume_uuid": HOME_UUID,
    }
    base.update(changes)
    return base


def backup(**changes) -> dict:
    base = {
        "snapshot_id": 400,
        "snapshot_uuid": BACKUP_UUID,
        "exists": True,
        "read_only": True,
        "boot_state_coherent": True,
        "files_verified": True,
        "recovery_overlay_flagged": True,
        "kernel_packages": ["linux-cachyos", "linux-cachyos-lts"],
    }
    base.update(changes)
    return base


class FakeOps:
    def __init__(self, evidence: dict | None = None, created_id: int = 400) -> None:
        self.created: list[str] = []
        self.waited: list[int] = []
        self.evidence = evidence or backup()
        self.created_id = created_id

    def create_emergency_snapshot(self, transaction_id: str) -> int:
        self.created.append(transaction_id)
        return self.created_id

    def wait_for_backup(self, snapshot_id: int) -> dict:
        self.waited.append(snapshot_id)
        return dict(self.evidence)


def expect_blocked(name: str, fn, expected: str | None = None) -> None:
    try:
        fn()
    except PreparationBlocked as exc:
        if expected is not None and expected not in exc.blockers:
            raise AssertionError(f"{name}: missing blocker {expected}: {exc.blockers}")
        print(f"PASS {name}")
        return
    except ValueError:
        if expected is not None:
            raise
        print(f"PASS {name}")
        return
    raise AssertionError(name)

def run_success() -> tuple[object, dict, FakeOps]:
    with tempfile.TemporaryDirectory(prefix="maho-l3-prep-") as td:
        ops = FakeOps()
        result = prepare_restore_transaction(
            plan(),
            source_revision=REV,
            target_snapshot_uuid=TARGET_UUID,
            home_evidence=home(),
            provider_evidence=provider(),
            machine_id=MID,
            boot_root=td,
            ops=ops,
            transaction_id=TX,
        )
        journal = read_journal(Path(result.journal_path))
        return result, journal, ops


def main() -> None:
    blockers = preparation_blockers(
        plan(),
        source_revision=REV,
        target_snapshot_uuid=TARGET_UUID,
        home_evidence=home(),
        provider_evidence=provider(),
    )
    check("exact normal-root evidence is preparation-ready", not blockers)
    check(
        "preparation contract rejects accidental restore authority",
        "preparation_plan_grants_restore" in preparation_blockers(
            plan(restore_authorized=True), source_revision=REV,
            target_snapshot_uuid=TARGET_UUID, home_evidence=home(),
            provider_evidence=provider(),
        ),
    )

    result, persisted, ops = run_success()
    check("preparation creates exactly one emergency snapshot", ops.created == [TX])
    check("preparation waits only for created snapshot", ops.waited == [400])
    check("prepared journal remains non-executing", persisted["phase"] == "prepared")
    check("prepared journal binds target generation", persisted["target"]["snapshot_id"] == 349)
    check("prepared journal binds target kernel identity", persisted["target"]["expected_kernel_version"] == "7.1.8-1-cachyos")
    check("prepared journal binds emergency backup", persisted["backup"] == {"snapshot_id": 400, "snapshot_uuid": BACKUP_UUID})
    check("prepared journal binds exact home identity", persisted["home"]["subvolume_uuid"] == HOME_UUID)
    check("preparation result exposes durable journal", Path(result.journal_path).name == f"{TX}.json")

    with tempfile.TemporaryDirectory(prefix="maho-l3-prep-block-") as td:
        ops = FakeOps()
        expect_blocked(
            "blocked plan performs zero snapshot creation",
            lambda: prepare_restore_transaction(
                plan(ready=False), source_revision=REV,
                target_snapshot_uuid=TARGET_UUID, home_evidence=home(),
                provider_evidence=provider(), machine_id=MID, boot_root=td,
                ops=ops, transaction_id=TX,
            ),
            "preparation_plan_not_ready",
        )
        check("blocked plan left host untouched", not ops.created and not ops.waited)

    with tempfile.TemporaryDirectory(prefix="maho-l3-prep-id-") as td:
        ops = FakeOps()
        expect_blocked(
            "invalid transaction identity is rejected before mutation",
            lambda: prepare_restore_transaction(
                plan(), source_revision=REV, target_snapshot_uuid=TARGET_UUID,
                home_evidence=home(), provider_evidence=provider(),
                machine_id=MID, boot_root=td, ops=ops,
                transaction_id="../../escape",
            ),
        )
        check("invalid transaction identity creates no snapshot", not ops.created)

    with tempfile.TemporaryDirectory(prefix="maho-l3-prep-mid-") as td:
        ops = FakeOps()
        expect_blocked(
            "invalid machine identity is rejected before mutation",
            lambda: prepare_restore_transaction(
                plan(), source_revision=REV, target_snapshot_uuid=TARGET_UUID,
                home_evidence=home(), provider_evidence=provider(),
                machine_id="../bad", boot_root=td, ops=ops, transaction_id=TX,
            ),
        )
        check("invalid machine identity creates no snapshot", not ops.created)

    with tempfile.TemporaryDirectory(prefix="maho-l3-prep-backup-") as td:
        ops = FakeOps(backup(files_verified=False))
        expect_blocked(
            "unverified emergency backup cannot create authority journal",
            lambda: prepare_restore_transaction(
                plan(), source_revision=REV, target_snapshot_uuid=TARGET_UUID,
                home_evidence=home(), provider_evidence=provider(),
                machine_id=MID, boot_root=td, ops=ops, transaction_id=TX,
            ),
            "backup_boot_files_unverified",
        )
        check("failed backup verification used one bounded snapshot", ops.created == [TX])
        check("failed backup verification wrote no journal", not list(Path(td).rglob("*.json")))

    with tempfile.TemporaryDirectory(prefix="maho-l3-prep-target-") as td:
        ops = FakeOps(backup(snapshot_id=349, snapshot_uuid=TARGET_UUID), created_id=349)
        expect_blocked(
            "emergency backup cannot alias restore target",
            lambda: prepare_restore_transaction(
                plan(), source_revision=REV, target_snapshot_uuid=TARGET_UUID,
                home_evidence=home(), provider_evidence=provider(),
                machine_id=MID, boot_root=td, ops=ops, transaction_id=TX,
            ),
            "backup_matches_target_snapshot",
        )

    print("ALL SYSTEM RESTORE PREPARATION CONTRACTS PASS")


if __name__ == "__main__":
    main()
