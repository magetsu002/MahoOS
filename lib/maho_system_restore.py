#!/usr/bin/env python3
"""Pure fail-closed planning for bounded MahoOS L3 system restore.

This module does not execute restore commands. It binds a requested recovery
generation to the currently booted Maho recovery OverlayFS and to the exact
provider/configuration that a later privileged transaction is allowed to use.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from maho_recovery_generation import RecoveryGeneration, RecoveryGenerationReport


@dataclass(frozen=True)
class SystemRestorePlan:
    schema_version: int
    generation_id: str
    snapshot_id: int
    provider_command: str
    provider_package: str
    provider_version: str
    root_filesystem_uuid: str
    root_snapshot_fsroot: str
    home_scope: str
    expected_kernel_sha256: str
    expected_initramfs_sha256: str
    campaign_ready: bool
    production_enabled: bool
    requires_confirmation: bool
    automatic_allowed: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _generation(report: RecoveryGenerationReport, generation_id: str) -> RecoveryGeneration | None:
    return next((item for item in report.generations if item.generation_id == generation_id), None)


def _tokens(value: Any) -> set[str]:
    return set(value.split()) if isinstance(value, str) else set()


def plan_system_restore(
    report: RecoveryGenerationReport,
    generation_id: str,
    policy: Mapping[str, Any],
    provider_evidence: Mapping[str, Any],
) -> SystemRestorePlan:
    """Return an immutable L3 preflight result without mutating the machine."""
    blockers: list[str] = []
    generation = _generation(report, generation_id)
    recovery_policy = _mapping(policy.get("recovery"))
    expected_provider = _mapping(recovery_policy.get("system_restore_provider"))
    platform = report.current_platform

    if generation is None:
        raise ValueError(f"unknown recovery generation: {generation_id}")

    sid = generation.snapshot.snapshot_id
    expected_fsroot = f"/@snapshots/{sid}/snapshot"
    if platform.get("recovery_overlay_active") is not True:
        blockers.append("recovery_overlay_not_active")
    if platform.get("root_fstype") != "btrfs":
        blockers.append("root_not_btrfs")
    if platform.get("root_fsroot") != expected_fsroot:
        blockers.append("booted_snapshot_root_mismatch")
    if platform.get("current_snapshot_id") != sid:
        blockers.append("requested_generation_not_current")
    if generation.snapshot.read_only is not True:
        blockers.append("snapshot_not_read_only")
    if generation.home_scope != "excluded":
        blockers.append("personal_data_scope_not_excluded")
    if generation.known_good is not True:
        blockers.append("generation_not_known_good")
    if generation.boot_state_coherent is not True:
        blockers.append("boot_state_not_coherent")
    if generation.boot.files_verified is not True:
        blockers.append("boot_files_unverified")
    if generation.boot.artifacts_coherent is not True:
        blockers.append("boot_artifacts_not_coherent")
    if generation.boot.recovery_overlay_flagged is not True:
        blockers.append("recovery_overlay_flag_unverified")

    allowed_rejections = {"current_failed_generation"}
    unexpected_rejections = set(generation.rejection_reasons) - allowed_rejections
    if unexpected_rejections:
        blockers.append("generation_has_unresolved_rejections")
    if "current_failed_generation" not in generation.rejection_reasons:
        blockers.append("generation_not_identified_as_current_recovery_boot")

    provider_path = provider_evidence.get("path")
    provider_package = provider_evidence.get("package")
    provider_version = provider_evidence.get("version")
    provider_uid = provider_evidence.get("uid")
    provider_mode = provider_evidence.get("mode")
    provider_config = _mapping(provider_evidence.get("config"))

    if provider_path != expected_provider.get("command"):
        blockers.append("provider_command_mismatch")
    if provider_package != expected_provider.get("package"):
        blockers.append("provider_package_mismatch")
    if provider_version != expected_provider.get("version"):
        blockers.append("provider_version_uncertified")
    if provider_uid != 0:
        blockers.append("provider_not_root_owned")
    if not isinstance(provider_mode, int) or provider_mode & 0o022:
        blockers.append("provider_permissions_unsafe")

    expected_config = {
        "RESTORE_METHOD": "replace",
        "ROOT_SUBVOLUME_PATH": "/@",
        "SET_SNAPSHOT_AS_DEFAULT": "no",
        "SNAPSHOT_WRITABLE": "no",
        "SNAPPER_CONFIG_NAME": generation.snapshot.config_name,
        "FS_UUID": generation.root_filesystem_uuid,
    }
    for key, expected in expected_config.items():
        if provider_config.get(key) != expected:
            blockers.append(f"provider_config_{key.lower()}_mismatch")

    cmdline = _tokens(provider_evidence.get("cmdline"))
    if "maho.recovery_snapshot=1" not in cmdline:
        blockers.append("kernel_recovery_flag_missing")
    if f"rootflags=subvol={expected_fsroot}" not in cmdline:
        blockers.append("kernel_snapshot_root_mismatch")

    kernel_hash = generation.boot.kernel_sha256_expected or ""
    initramfs_hash = generation.boot.initramfs_sha256_expected or ""
    if not kernel_hash or generation.boot.kernel_sha256_observed != kernel_hash:
        blockers.append("kernel_hash_not_verified")
    if not initramfs_hash or generation.boot.initramfs_sha256_observed != initramfs_hash:
        blockers.append("initramfs_hash_not_verified")

    blockers = list(dict.fromkeys(blockers))
    campaign_ready = not blockers
    production_enabled = bool(
        campaign_ready
        and report.native_restore_enabled
        and report.certified_system_restore_plannable
        and _mapping(policy.get("boot")).get("kernel_update_snapshot_restore_certified") is True
    )
    return SystemRestorePlan(
        schema_version=1,
        generation_id=generation_id,
        snapshot_id=sid,
        provider_command=str(expected_provider.get("command") or ""),
        provider_package=str(expected_provider.get("package") or ""),
        provider_version=str(expected_provider.get("version") or ""),
        root_filesystem_uuid=generation.root_filesystem_uuid or "",
        root_snapshot_fsroot=expected_fsroot,
        home_scope=generation.home_scope,
        expected_kernel_sha256=kernel_hash,
        expected_initramfs_sha256=initramfs_hash,
        campaign_ready=campaign_ready,
        production_enabled=production_enabled,
        requires_confirmation=True,
        automatic_allowed=False,
        blockers=tuple(blockers),
    )
