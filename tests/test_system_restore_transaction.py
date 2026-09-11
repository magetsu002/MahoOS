#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_system_restore_journal import create_journal, read_journal, write_journal  # noqa: E402
from maho_system_restore_provider import ProviderRunResult  # noqa: E402
from maho_system_restore_transaction import (  # noqa: E402
    PostBootEvidence,
    StructuralEvidence,
    TransactionBlocked,
    authorize_execution,
    execute_prepared_restore,
    postboot_blockers,
    structural_blockers,
    verify_postboot_restore,
)

REV = "a" * 40
TX = "l3-20260911T120000Z-deadbeef"
GID = "g3-0123456789abcdef01234567"
ROOT_FS = "11111111-2222-3333-4444-555555555555"
TARGET_UUID = "target-snapshot-uuid"
BACKUP_UUID = "backup-snapshot-uuid"
HOME_FS = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
HOME_UUID = "home-subvolume-uuid"
KHASH = "1" * 64
IHASH = "2" * 64


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def journal() -> dict:
    return create_journal(
        transaction_id=TX,
        source_revision=REV,
        target={
            "generation_id": GID,
            "snapshot_id": 349,
            "snapshot_uuid": TARGET_UUID,
            "root_filesystem_uuid": ROOT_FS,
            "expected_kernel_package": "linux-cachyos",
            "expected_kernel_version": "7.1.8-1",
            "expected_kernel_sha256": KHASH,
            "expected_initramfs_sha256": IHASH,
        },
        backup={"snapshot_id": 400, "snapshot_uuid": BACKUP_UUID},
        home={
            "filesystem_uuid": HOME_FS,
            "fsroot": "/@home",
            "subvolume_uuid": HOME_UUID,
        },
        provider={
            "command": "/usr/bin/limine-snapper-restore",
            "package": "limine-snapper-sync",
            "version": "1.31.0-1",
        },
    )


def plan(**changes) -> dict:
    base = {
        "campaign_ready": True,
        "automatic_allowed": False,
        "requires_confirmation": True,
        "generation_id": GID,
        "snapshot_id": 349,
        "root_filesystem_uuid": ROOT_FS,
        "expected_kernel_package": "linux-cachyos",
        "expected_kernel_version": "7.1.8-1",
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


def backup(**changes) -> dict:
    base = {
        "snapshot_id": 400,
        "snapshot_uuid": BACKUP_UUID,
        "exists": True,
        "read_only": True,
        "boot_state_coherent": True,
        "files_verified": True,
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


def structural(**changes) -> StructuralEvidence:
    base = {
        "root_filesystem_uuid": ROOT_FS,
        "root_parent_uuid": TARGET_UUID,
        "root_fsroot": "/@",
        "kernel_sha256": KHASH,
        "initramfs_sha256": IHASH,
        "home_filesystem_uuid": HOME_FS,
        "home_fsroot": "/@home",
        "home_subvolume_uuid": HOME_UUID,
        "backup_snapshot_uuid": BACKUP_UUID,
        "backup_read_only": True,
    }
    base.update(changes)
    return StructuralEvidence(**base)


def postboot(**changes) -> PostBootEvidence:
    base = {
        "root_filesystem_uuid": ROOT_FS,
        "root_parent_uuid": TARGET_UUID,
        "root_fstype": "btrfs",
        "root_fsroot": "/@",
        "recovery_overlay_active": False,
        "recovery_flag_present": False,
        "kernel_package": "linux-cachyos",
        "kernel_version": "7.1.8-1",
        "running_kernel_version": "7.1.8-1-cachyos",
        "running_kernel_sha256": KHASH,
        "kernel_sha256": KHASH,
        "initramfs_sha256": IHASH,
        "home_filesystem_uuid": HOME_FS,
        "home_fsroot": "/@home",
        "home_subvolume_uuid": HOME_UUID,
        "backup_snapshot_uuid": BACKUP_UUID,
        "backup_read_only": True,
    }
    base.update(changes)
    return PostBootEvidence(**base)


def successful_runner(counter: list[int]):
    def run(dialogue):
        counter[0] += 1
        dialogue.feed("Snapshot ID     : 349\n")
        dialogue.feed("Restore snapshot 349 (method: replace)?\nChoice [r/l/c]: ")
        dialogue.feed("Description for backup subvolume @: ")
        dialogue.feed("Restoring snapshot 349...\n")
        return ProviderRunResult(0, dialogue.mutation_started, "ok")
    return run


def execute_case(*, runner=None, collector=None, **gate_changes):
    with tempfile.TemporaryDirectory(prefix="maho-l3-transaction-") as td:
        path = Path(td) / f"{TX}.json"
        write_journal(path, journal())
        args = {
            "source_revision": REV,
            "plan": plan(),
            "provider_evidence": provider(),
            "target_snapshot_uuid": TARGET_UUID,
            "backup_evidence": backup(),
            "home_evidence": home(),
        }
        args.update(gate_changes)
        count = [0]
        result = execute_prepared_restore(
            path,
            **args,
            provider_runner=runner or successful_runner(count),
            structural_collector=collector or structural,
        )
        return result, read_journal(path), count[0]


def main() -> None:
    gate = authorize_execution(
        journal(),
        source_revision=REV,
        plan=plan(),
        provider_evidence=provider(),
        target_snapshot_uuid=TARGET_UUID,
        backup_evidence=backup(),
        home_evidence=home(),
    )
    check("exact prepared transaction is authorized", gate.authorized and not gate.blockers)

    drift = authorize_execution(
        journal(),
        source_revision="b" * 40,
        plan=plan(),
        provider_evidence=provider(),
        target_snapshot_uuid=TARGET_UUID,
        backup_evidence=backup(),
        home_evidence=home(),
    )
    check("source revision drift blocks execution", "source_revision_mismatch" in drift.blockers)

    missing_backup = authorize_execution(
        journal(),
        source_revision=REV,
        plan=plan(),
        provider_evidence=provider(),
        target_snapshot_uuid=TARGET_UUID,
        backup_evidence=backup(exists=False),
        home_evidence=home(),
    )
    check("missing emergency backup blocks execution", "backup_snapshot_missing" in missing_backup.blockers)

    home_drift = authorize_execution(
        journal(),
        source_revision=REV,
        plan=plan(),
        provider_evidence=provider(),
        target_snapshot_uuid=TARGET_UUID,
        backup_evidence=backup(),
        home_evidence=home(subvolume_uuid="other-home"),
    )
    check("home identity drift blocks execution", "home_subvolume_uuid_mismatch" in home_drift.blockers)

    provider_drift = authorize_execution(
        journal(),
        source_revision=REV,
        plan=plan(),
        provider_evidence=provider(version="1.32.0-1"),
        target_snapshot_uuid=TARGET_UUID,
        backup_evidence=backup(),
        home_evidence=home(),
    )
    check("provider version drift blocks execution", "provider_version_mismatch" in provider_drift.blockers)

    bad_parent = structural_blockers(
        journal(), structural(root_parent_uuid="wrong-parent")
    )
    check("restored root must descend from exact target snapshot", "restored_root_parent_uuid_mismatch" in bad_parent)

    bad_home = structural_blockers(
        journal(), structural(home_subvolume_uuid="wrong-home")
    )
    check("post-provider home identity is immutable", "restored_home_subvolume_mismatch" in bad_home)

    result, persisted, count = execute_case()
    check("exact provider is invoked once", count == 1)
    check("successful restore reaches reboot-ready state", result.phase == "restored-awaiting-reboot")
    check("successful restore records mutation", result.mutation_started is True)
    check("successful restore has no structural blockers", not result.blockers)
    check(
        "journal preserves exact bounded phase order",
        [row["phase"] for row in persisted["history"]] == [
            "prepared", "restore-started", "provider-returned", "restored-awaiting-reboot"
        ],
    )

    verify_result, verify_journal, _ = execute_case(
        collector=lambda: structural(root_parent_uuid="wrong-parent")
    )
    check("structural mismatch terminates at verify-failed", verify_result.phase == "verify-failed")
    check("verify failure never reaches reboot-ready", verify_journal["phase"] == "verify-failed")

    def explode(_dialogue):
        raise RuntimeError("synthetic provider failure")

    failed_result, failed_journal, _ = execute_case(runner=explode)
    check("provider exception becomes durable provider-failed", failed_result.phase == "provider-failed")
    check("provider failure is terminal in journal", failed_journal["phase"] == "provider-failed")

    def nonzero(dialogue):
        dialogue.feed("Snapshot ID     : 349\n")
        dialogue.feed("Restore snapshot 349 (method: replace)?\nChoice [r/l/c]: ")
        dialogue.feed("Description for backup subvolume @: ")
        dialogue.feed("Restoring snapshot 349...\n")
        return ProviderRunResult(7, True, "synthetic failure")

    nonzero_result, nonzero_journal, _ = execute_case(runner=nonzero)
    check("nonzero provider exit is never accepted", nonzero_result.phase == "provider-failed")
    check("nonzero provider exit cannot advance journal", nonzero_journal["phase"] == "provider-failed")

    with tempfile.TemporaryDirectory(prefix="maho-l3-blocked-") as td:
        path = Path(td) / f"{TX}.json"
        write_journal(path, journal())
        calls = [0]

        def forbidden(_dialogue):
            calls[0] += 1
            raise AssertionError("blocked transaction reached provider")

        try:
            execute_prepared_restore(
                path,
                source_revision="b" * 40,
                plan=plan(),
                provider_evidence=provider(),
                target_snapshot_uuid=TARGET_UUID,
                backup_evidence=backup(),
                home_evidence=home(),
                provider_runner=forbidden,
                structural_collector=structural,
            )
        except TransactionBlocked:
            pass
        else:
            raise AssertionError("blocked transaction must raise")
        blocked = read_journal(path)
        check("blocked gate never invokes provider", calls[0] == 0)
        check("blocked gate leaves journal prepared", blocked["phase"] == "prepared")

    with tempfile.TemporaryDirectory(prefix="maho-l3-postboot-") as td:
        path = Path(td) / f"{TX}.json"
        write_journal(path, journal())
        execute_prepared_restore(
            path,
            source_revision=REV,
            plan=plan(),
            provider_evidence=provider(),
            target_snapshot_uuid=TARGET_UUID,
            backup_evidence=backup(),
            home_evidence=home(),
            provider_runner=successful_runner([0]),
            structural_collector=structural,
        )
        proof = verify_postboot_restore(path, postboot())
        final = read_journal(path)
        check("normal-root postboot proof finalizes transaction", proof.phase == "structural-verified")
        check("successful postboot proof is durable", final["phase"] == "structural-verified")

    bad_running = postboot_blockers(
        {**journal(), "phase": "restored-awaiting-reboot", "history": [
            journal()["history"][0],
            {"phase": "restore-started", "at": journal()["created_at"]},
            {"phase": "provider-returned", "at": journal()["created_at"]},
            {"phase": "restored-awaiting-reboot", "at": journal()["created_at"]},
        ]},
        postboot(running_kernel_sha256="9" * 64),
    )
    check("postboot binds the running kernel to the target image", "running_kernel_hash_mismatch" in bad_running)

    with tempfile.TemporaryDirectory(prefix="maho-l3-postboot-fail-") as td:
        path = Path(td) / f"{TX}.json"
        write_journal(path, journal())
        execute_prepared_restore(
            path, source_revision=REV, plan=plan(), provider_evidence=provider(),
            target_snapshot_uuid=TARGET_UUID, backup_evidence=backup(), home_evidence=home(),
            provider_runner=successful_runner([0]), structural_collector=structural,
        )
        failed = verify_postboot_restore(path, postboot(recovery_flag_present=True))
        check("recovery-flagged reboot is terminal verify failure", failed.phase == "verify-failed")

    print("ALL SYSTEM RESTORE TRANSACTION CONTRACTS PASS")


if __name__ == "__main__":
    main()
