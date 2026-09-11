#!/usr/bin/env python3
"""Normal-root preparation for one bounded MahoOS L3 restore transaction."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Mapping, Protocol

from maho_system_restore_journal import (
    create_journal,
    journal_path,
    new_transaction_id,
    write_journal,
)

_REVISION = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
PINNED_COMMAND = "/usr/bin/limine-snapper-restore"
PINNED_PACKAGE = "limine-snapper-sync"
PINNED_VERSION = "1.31.0-1"


class PreparationBlocked(RuntimeError):
    def __init__(self, blockers: tuple[str, ...]):
        super().__init__("L3 preparation blocked: " + ", ".join(blockers))
        self.blockers = blockers


class PreparationOps(Protocol):
    def create_emergency_snapshot(self, transaction_id: str) -> int: ...
    def wait_for_backup(self, snapshot_id: int) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class PreparationResult:
    transaction_id: str
    journal_path: str
    backup_snapshot_id: int
    backup_snapshot_uuid: str


def _plan_dict(plan: Any) -> Mapping[str, Any]:
    if isinstance(plan, Mapping):
        return plan
    as_dict = getattr(plan, "as_dict", None)
    if callable(as_dict):
        value = as_dict()
        if isinstance(value, Mapping):
            return value
    raise ValueError("system restore preparation plan is not serializable")


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def preparation_blockers(
    plan: Any,
    *,
    source_revision: str,
    target_snapshot_uuid: str,
    home_evidence: Mapping[str, Any],
    provider_evidence: Mapping[str, Any],
) -> tuple[str, ...]:
    p = _plan_dict(plan)
    blockers: list[str] = []
    if p.get("ready") is not True:
        blockers.append("preparation_plan_not_ready")
    if p.get("restore_authorized") is not False:
        blockers.append("preparation_plan_grants_restore")
    if not _REVISION.fullmatch(source_revision):
        blockers.append("source_revision_invalid")
    if not isinstance(p.get("generation_id"), str) or not str(p["generation_id"]).startswith("g3-"):
        blockers.append("target_generation_invalid")
    if not isinstance(p.get("snapshot_id"), int) or int(p["snapshot_id"]) <= 0:
        blockers.append("target_snapshot_invalid")
    if not isinstance(target_snapshot_uuid, str) or not target_snapshot_uuid:
        blockers.append("target_snapshot_uuid_missing")
    if not isinstance(p.get("root_filesystem_uuid"), str) or not p["root_filesystem_uuid"]:
        blockers.append("target_root_filesystem_missing")
    if not isinstance(p.get("expected_kernel_package"), str) or not p["expected_kernel_package"]:
        blockers.append("target_kernel_package_missing")
    if not isinstance(p.get("expected_kernel_version"), str) or not p["expected_kernel_version"]:
        blockers.append("target_kernel_version_missing")
    for key in ("expected_kernel_sha256", "expected_initramfs_sha256"):
        value = p.get(key)
        if not isinstance(value, str) or not _SHA256.fullmatch(value):
            blockers.append(f"target_{key}_invalid")

    for key in ("filesystem_uuid", "fsroot", "subvolume_uuid"):
        value = home_evidence.get(key)
        if not isinstance(value, str) or not value:
            blockers.append(f"home_{key}_missing")
    if home_evidence.get("fsroot") != "/@home":
        blockers.append("home_fsroot_unexpected")

    if provider_evidence.get("path") != PINNED_COMMAND or p.get("provider_command") != PINNED_COMMAND:
        blockers.append("provider_command_mismatch")
    if provider_evidence.get("package") != PINNED_PACKAGE or p.get("provider_package") != PINNED_PACKAGE:
        blockers.append("provider_package_mismatch")
    if provider_evidence.get("version") != PINNED_VERSION or p.get("provider_version") != PINNED_VERSION:
        blockers.append("provider_version_mismatch")
    if provider_evidence.get("uid") != 0 or provider_evidence.get("regular_file") is not True:
        blockers.append("provider_identity_unsafe")
    mode = provider_evidence.get("mode")
    if not isinstance(mode, int) or mode & 0o022:
        blockers.append("provider_permissions_unsafe")
    if provider_evidence.get("package_owns_command") is not True:
        blockers.append("provider_ownership_unverified")
    if provider_evidence.get("package_files_ok") is not True:
        blockers.append("provider_integrity_unverified")
    return _unique(blockers)


def _backup_blockers(
    target_snapshot_id: int,
    target_snapshot_uuid: str,
    backup: Mapping[str, Any],
) -> tuple[str, ...]:
    blockers: list[str] = []
    sid = backup.get("snapshot_id")
    if not isinstance(sid, int) or sid <= 0:
        blockers.append("backup_snapshot_id_invalid")
    elif sid == target_snapshot_id:
        blockers.append("backup_matches_target_snapshot")
    uuid = backup.get("snapshot_uuid")
    if not isinstance(uuid, str) or not uuid:
        blockers.append("backup_snapshot_uuid_missing")
    elif uuid == target_snapshot_uuid:
        blockers.append("backup_matches_target_uuid")
    if backup.get("exists") is not True:
        blockers.append("backup_snapshot_missing")
    if backup.get("read_only") is not True:
        blockers.append("backup_snapshot_not_read_only")
    if backup.get("boot_state_coherent") is not True:
        blockers.append("backup_boot_state_not_coherent")
    if backup.get("files_verified") is not True:
        blockers.append("backup_boot_files_unverified")
    if backup.get("recovery_overlay_flagged") is not True:
        blockers.append("backup_recovery_overlay_unverified")
    packages = backup.get("kernel_packages")
    if not isinstance(packages, (list, tuple, set)):
        blockers.append("backup_kernel_set_missing")
    else:
        present = {str(item) for item in packages}
        required = {"linux-cachyos", "linux-cachyos-lts"}
        if not required.issubset(present):
            blockers.append("backup_kernel_set_incomplete")
    return _unique(blockers)


def prepare_restore_transaction(
    plan: Any,
    *,
    source_revision: str,
    target_snapshot_uuid: str,
    home_evidence: Mapping[str, Any],
    provider_evidence: Mapping[str, Any],
    machine_id: str,
    boot_root: str | Path,
    ops: PreparationOps,
    transaction_id: str | None = None,
) -> PreparationResult:
    """Create one emergency backup and durable prepared journal; never authorizes restore."""
    p = _plan_dict(plan)
    blockers = preparation_blockers(
        p,
        source_revision=source_revision,
        target_snapshot_uuid=target_snapshot_uuid,
        home_evidence=home_evidence,
        provider_evidence=provider_evidence,
    )
    if blockers:
        raise PreparationBlocked(blockers)

    txid = transaction_id or new_transaction_id()
    path = journal_path(boot_root, machine_id, txid)
    backup_snapshot_id = ops.create_emergency_snapshot(txid)
    if not isinstance(backup_snapshot_id, int) or backup_snapshot_id <= 0:
        raise PreparationBlocked(("backup_snapshot_creation_invalid",))
    backup = dict(ops.wait_for_backup(backup_snapshot_id))
    if backup.get("snapshot_id") != backup_snapshot_id:
        raise PreparationBlocked(("backup_snapshot_identity_mismatch",))
    backup_blockers = _backup_blockers(
        int(p["snapshot_id"]),
        target_snapshot_uuid,
        backup,
    )
    if backup_blockers:
        raise PreparationBlocked(backup_blockers)

    journal = create_journal(
        transaction_id=txid,
        source_revision=source_revision,
        target={
            "generation_id": p["generation_id"],
            "snapshot_id": p["snapshot_id"],
            "snapshot_uuid": target_snapshot_uuid,
            "root_filesystem_uuid": p["root_filesystem_uuid"],
            "expected_kernel_package": p["expected_kernel_package"],
            "expected_kernel_version": p["expected_kernel_version"],
            "expected_kernel_sha256": p["expected_kernel_sha256"],
            "expected_initramfs_sha256": p["expected_initramfs_sha256"],
        },
        backup={
            "snapshot_id": backup_snapshot_id,
            "snapshot_uuid": backup["snapshot_uuid"],
        },
        home={
            "filesystem_uuid": home_evidence["filesystem_uuid"],
            "fsroot": home_evidence["fsroot"],
            "subvolume_uuid": home_evidence["subvolume_uuid"],
        },
        provider={
            "command": PINNED_COMMAND,
            "package": PINNED_PACKAGE,
            "version": PINNED_VERSION,
        },
    )
    write_journal(path, journal)
    return PreparationResult(
        transaction_id=txid,
        journal_path=str(path),
        backup_snapshot_id=backup_snapshot_id,
        backup_snapshot_uuid=str(backup["snapshot_uuid"]),
    )
