#!/usr/bin/env python3
"""Fail-closed coordinator for one bounded MahoOS L3 restore attempt."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, Mapping

from maho_system_restore_journal import (
    read_journal,
    transition_journal,
    validate_journal,
    write_journal,
)
from maho_system_restore_provider import (
    ProviderDialogue,
    ProviderProtocolError,
    ProviderRunResult,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
PINNED_COMMAND = "/usr/bin/limine-snapper-restore"
PINNED_PACKAGE = "limine-snapper-sync"
PINNED_VERSION = "1.31.0-1"


@dataclass(frozen=True)
class ExecutionGate:
    authorized: bool
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class StructuralEvidence:
    root_filesystem_uuid: str
    root_parent_uuid: str
    root_fsroot: str
    kernel_sha256: str
    initramfs_sha256: str
    home_filesystem_uuid: str
    home_fsroot: str
    home_subvolume_uuid: str
    backup_snapshot_uuid: str
    backup_read_only: bool


@dataclass(frozen=True)
class TransactionResult:
    phase: str
    provider_returncode: int
    mutation_started: bool
    blockers: tuple[str, ...]


def _plan_dict(plan: Any) -> Mapping[str, Any]:
    if isinstance(plan, Mapping):
        return plan
    as_dict = getattr(plan, "as_dict", None)
    if callable(as_dict):
        value = as_dict()
        if isinstance(value, Mapping):
            return value
    raise ValueError("system restore plan is not serializable")


def _unique(values: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def authorize_execution(
    journal: Mapping[str, Any],
    *,
    source_revision: str,
    plan: Any,
    provider_evidence: Mapping[str, Any],
    target_snapshot_uuid: str,
    backup_evidence: Mapping[str, Any],
    home_evidence: Mapping[str, Any],
) -> ExecutionGate:
    """Re-authorize a prepared transaction from fresh recovery-boot evidence."""
    data = validate_journal(journal)
    p = _plan_dict(plan)
    blockers: list[str] = []
    target = data["target"]
    backup = data["backup"]
    home = data["home"]
    provider = data["provider"]

    if data["phase"] != "prepared":
        blockers.append("journal_not_prepared")
    if not _REVISION.fullmatch(source_revision) or source_revision != data["source_revision"]:
        blockers.append("source_revision_mismatch")
    if p.get("campaign_ready") is not True:
        blockers.append("restore_plan_not_campaign_ready")
    if p.get("automatic_allowed") is not False or p.get("requires_confirmation") is not True:
        blockers.append("restore_plan_consent_contract_invalid")
    if p.get("generation_id") != target.get("generation_id"):
        blockers.append("target_generation_mismatch")
    if p.get("snapshot_id") != target.get("snapshot_id"):
        blockers.append("target_snapshot_mismatch")
    if target_snapshot_uuid != target.get("snapshot_uuid"):
        blockers.append("target_snapshot_uuid_mismatch")
    if p.get("root_filesystem_uuid") != target.get("root_filesystem_uuid"):
        blockers.append("target_root_filesystem_mismatch")
    if p.get("expected_kernel_package") != target.get("expected_kernel_package"):
        blockers.append("target_kernel_package_mismatch")
    if p.get("expected_kernel_version") != target.get("expected_kernel_version"):
        blockers.append("target_kernel_version_mismatch")
    if p.get("expected_kernel_sha256") != target.get("expected_kernel_sha256"):
        blockers.append("target_kernel_hash_mismatch")
    if p.get("expected_initramfs_sha256") != target.get("expected_initramfs_sha256"):
        blockers.append("target_initramfs_hash_mismatch")

    if provider_evidence.get("path") != PINNED_COMMAND or provider.get("command") != PINNED_COMMAND:
        blockers.append("provider_command_mismatch")
    if provider_evidence.get("package") != PINNED_PACKAGE or provider.get("package") != PINNED_PACKAGE:
        blockers.append("provider_package_mismatch")
    if provider_evidence.get("version") != PINNED_VERSION or provider.get("version") != PINNED_VERSION:
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
    if backup_evidence.get("snapshot_id") != backup.get("snapshot_id"):
        blockers.append("backup_snapshot_mismatch")
    if backup_evidence.get("snapshot_uuid") != backup.get("snapshot_uuid"):
        blockers.append("backup_snapshot_uuid_mismatch")
    if backup_evidence.get("exists") is not True:
        blockers.append("backup_snapshot_missing")
    if backup_evidence.get("read_only") is not True:
        blockers.append("backup_snapshot_not_read_only")
    if backup_evidence.get("boot_state_coherent") is not True:
        blockers.append("backup_boot_state_not_coherent")
    if backup_evidence.get("files_verified") is not True:
        blockers.append("backup_boot_files_unverified")

    for key in ("filesystem_uuid", "fsroot", "subvolume_uuid"):
        expected = home.get(key)
        if not isinstance(expected, str) or not expected:
            blockers.append(f"journal_home_{key}_missing")
        elif home_evidence.get(key) != expected:
            blockers.append(f"home_{key}_mismatch")

    return ExecutionGate(authorized=not blockers, blockers=_unique(blockers))


def structural_blockers(
    journal: Mapping[str, Any], evidence: StructuralEvidence
) -> tuple[str, ...]:
    data = validate_journal(journal)
    target = data["target"]
    backup = data["backup"]
    home = data["home"]
    blockers: list[str] = []

    if evidence.root_filesystem_uuid != target.get("root_filesystem_uuid"):
        blockers.append("restored_root_filesystem_mismatch")
    if evidence.root_fsroot != "/@":
        blockers.append("restored_root_fsroot_mismatch")
    if evidence.root_parent_uuid != target.get("snapshot_uuid"):
        blockers.append("restored_root_parent_uuid_mismatch")
    if evidence.kernel_sha256 != target.get("expected_kernel_sha256"):
        blockers.append("restored_kernel_hash_mismatch")
    if evidence.initramfs_sha256 != target.get("expected_initramfs_sha256"):
        blockers.append("restored_initramfs_hash_mismatch")

    if evidence.home_filesystem_uuid != home.get("filesystem_uuid"):
        blockers.append("restored_home_filesystem_mismatch")
    if evidence.home_fsroot != home.get("fsroot"):
        blockers.append("restored_home_fsroot_mismatch")
    if evidence.home_subvolume_uuid != home.get("subvolume_uuid"):
        blockers.append("restored_home_subvolume_mismatch")
    if evidence.backup_snapshot_uuid != backup.get("snapshot_uuid"):
        blockers.append("emergency_backup_identity_mismatch")
    if evidence.backup_read_only is not True:
        blockers.append("emergency_backup_not_read_only")

    for value, name in (
        (evidence.kernel_sha256, "kernel"),
        (evidence.initramfs_sha256, "initramfs"),
    ):
        if not _SHA256.fullmatch(value):
            blockers.append(f"restored_{name}_hash_invalid")
    return _unique(blockers)


class TransactionBlocked(RuntimeError):
    def __init__(self, blockers: tuple[str, ...]):
        super().__init__("L3 restore blocked: " + ", ".join(blockers))
        self.blockers = blockers


def _persist_transition(
    path: Path,
    journal: Mapping[str, Any],
    phase: str,
    *,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    updated = transition_journal(journal, phase, details=details)
    write_journal(path, updated)
    return updated


def execute_prepared_restore(
    journal_path: str | Path,
    *,
    source_revision: str,
    plan: Any,
    provider_evidence: Mapping[str, Any],
    target_snapshot_uuid: str,
    backup_evidence: Mapping[str, Any],
    home_evidence: Mapping[str, Any],
    provider_runner: Callable[[ProviderDialogue], ProviderRunResult],
    structural_collector: Callable[[], StructuralEvidence],
) -> TransactionResult:
    """Execute one prepared restore attempt; never retries or reselects a target."""
    path = Path(journal_path)
    journal = read_journal(path)
    gate = authorize_execution(
        journal,
        source_revision=source_revision,
        plan=plan,
        provider_evidence=provider_evidence,
        target_snapshot_uuid=target_snapshot_uuid,
        backup_evidence=backup_evidence,
        home_evidence=home_evidence,
    )
    if not gate.authorized:
        raise TransactionBlocked(gate.blockers)

    dialogue = ProviderDialogue(
        int(journal["target"]["snapshot_id"]),
        str(journal["transaction_id"]),
    )
    journal = _persist_transition(
        path,
        journal,
        "restore-started",
        details={"automatic": False, "attempt": 1},
    )

    try:
        provider_result = provider_runner(dialogue)
    except Exception as exc:
        failed = _persist_transition(
            path,
            journal,
            "provider-failed",
            details={
                "error": type(exc).__name__,
                "mutation_started": dialogue.mutation_started,
            },
        )
        return TransactionResult(failed["phase"], -1, dialogue.mutation_started, ("provider_failed",))
    if provider_result.returncode != 0 or provider_result.mutation_started is not True:
        failed = _persist_transition(
            path,
            journal,
            "provider-failed",
            details={
                "exit_code": provider_result.returncode,
                "mutation_started": provider_result.mutation_started,
            },
        )
        return TransactionResult(
            failed["phase"],
            provider_result.returncode,
            provider_result.mutation_started,
            ("provider_failed",),
        )

    journal = _persist_transition(
        path,
        journal,
        "provider-returned",
        details={"exit_code": 0, "mutation_started": True},
    )

    try:
        structural = structural_collector()
        blockers = structural_blockers(journal, structural)
    except Exception as exc:
        blockers = (f"structural_collection_failed:{type(exc).__name__}",)
    if blockers:
        failed = _persist_transition(
            path,
            journal,
            "verify-failed",
            details={"blockers": list(blockers)},
        )
        return TransactionResult(
            failed["phase"],
            provider_result.returncode,
            provider_result.mutation_started,
            blockers,
        )

    awaiting = _persist_transition(
        path,
        journal,
        "restored-awaiting-reboot",
        details={"structural_verification": "passed"},
    )
    return TransactionResult(
        awaiting["phase"],
        provider_result.returncode,
        provider_result.mutation_started,
        (),
    )


@dataclass(frozen=True)
class PostBootEvidence:
    root_filesystem_uuid: str
    root_parent_uuid: str
    root_fstype: str
    root_fsroot: str
    recovery_overlay_active: bool
    recovery_flag_present: bool
    kernel_package: str
    kernel_version: str
    running_kernel_version: str
    kernel_sha256: str
    initramfs_sha256: str
    home_filesystem_uuid: str
    home_fsroot: str
    home_subvolume_uuid: str
    backup_snapshot_uuid: str
    backup_read_only: bool


def postboot_blockers(
    journal: Mapping[str, Any], evidence: PostBootEvidence
) -> tuple[str, ...]:
    data = validate_journal(journal)
    target = data["target"]
    backup = data["backup"]
    home = data["home"]
    blockers: list[str] = []

    if data["phase"] != "restored-awaiting-reboot":
        blockers.append("journal_not_awaiting_reboot_verification")
    if evidence.recovery_overlay_active:
        blockers.append("recovery_overlay_still_active")
    if evidence.recovery_flag_present:
        blockers.append("recovery_kernel_flag_still_present")
    if evidence.root_fstype != "btrfs":
        blockers.append("postboot_root_not_btrfs")
    if evidence.root_fsroot != "/@":
        blockers.append("postboot_root_fsroot_mismatch")
    if evidence.root_filesystem_uuid != target.get("root_filesystem_uuid"):
        blockers.append("postboot_root_filesystem_mismatch")
    if evidence.root_parent_uuid != target.get("snapshot_uuid"):
        blockers.append("postboot_root_parent_uuid_mismatch")
    if evidence.kernel_package != target.get("expected_kernel_package"):
        blockers.append("postboot_kernel_package_mismatch")
    if evidence.kernel_version != target.get("expected_kernel_version"):
        blockers.append("postboot_kernel_version_mismatch")
    if evidence.running_kernel_version != target.get("expected_kernel_version"):
        blockers.append("running_kernel_version_mismatch")
    if evidence.kernel_sha256 != target.get("expected_kernel_sha256"):
        blockers.append("postboot_kernel_hash_mismatch")
    if evidence.initramfs_sha256 != target.get("expected_initramfs_sha256"):
        blockers.append("postboot_initramfs_hash_mismatch")
    if evidence.home_filesystem_uuid != home.get("filesystem_uuid"):
        blockers.append("postboot_home_filesystem_mismatch")
    if evidence.home_fsroot != home.get("fsroot"):
        blockers.append("postboot_home_fsroot_mismatch")
    if evidence.home_subvolume_uuid != home.get("subvolume_uuid"):
        blockers.append("postboot_home_subvolume_mismatch")
    if evidence.backup_snapshot_uuid != backup.get("snapshot_uuid"):
        blockers.append("postboot_emergency_backup_identity_mismatch")
    if evidence.backup_read_only is not True:
        blockers.append("postboot_emergency_backup_not_read_only")
    for value, name in (
        (evidence.kernel_sha256, "kernel"),
        (evidence.initramfs_sha256, "initramfs"),
    ):
        if not _SHA256.fullmatch(value):
            blockers.append(f"postboot_{name}_hash_invalid")
    return _unique(blockers)


def verify_postboot_restore(
    journal_path: str | Path,
    evidence: PostBootEvidence,
) -> TransactionResult:
    """Finalize one restore only after normal-root post-boot structural proof."""
    path = Path(journal_path)
    journal = read_journal(path)
    if journal["phase"] != "restored-awaiting-reboot":
        raise TransactionBlocked(("journal_not_awaiting_reboot_verification",))

    blockers = postboot_blockers(journal, evidence)
    if blockers:
        failed = _persist_transition(
            path,
            journal,
            "verify-failed",
            details={"stage": "postboot", "blockers": list(blockers)},
        )
        return TransactionResult(failed["phase"], 0, True, blockers)
    verified = _persist_transition(
        path,
        journal,
        "structural-verified",
        details={
            "stage": "postboot",
            "normal_root": True,
            "running_kernel_version": evidence.running_kernel_version,
            "home_preserved": True,
            "emergency_backup_preserved": True,
        },
    )
    return TransactionResult(
        verified["phase"],
        0,
        True,
        (),
    )
