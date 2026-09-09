#!/usr/bin/env python3
"""Pure Guardian G3 recovery-generation model.

A recovery generation is deliberately stronger than a Snapper snapshot.  The
identity is derived from the Btrfs filesystem UUID, Snapper config name and
numeric snapshot ID.  Those are the smallest platform identifiers that remain
stable across display-name/description/time changes while avoiding collisions
when a filesystem is recreated and snapshot numbers are reused.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SnapshotEvidence:
    config_name: str
    snapshot_id: int
    creation_time: str | None
    subvolume: str | None
    snapshot_type: str | None
    cleanup: str | None
    description: str | None
    userdata: Mapping[str, str] = field(default_factory=dict)
    pre_number: int | None = None
    active: bool | None = None
    default: bool | None = None
    read_only: bool | None = None
    package_transaction: str = "unknown"


@dataclass(frozen=True)
class BootEvidence:
    source: str = "unavailable"
    entry_id: str | None = None
    kernel_package: str | None = None
    kernel_version: str | None = None
    kernel_path: str | None = None
    initramfs_path: str | None = None
    snapshot_id: int | None = None
    filesystem_uuid: str | None = None
    files_verified: bool | None = None
    artifacts_coherent: bool | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RecoveryGeneration:
    generation_id: str | None
    snapshot: SnapshotEvidence
    root_filesystem_uuid: str | None
    root_source: str | None
    root_fsroot: str | None
    home_scope: str
    boot: BootEvidence
    lts_kernel_present: bool
    known_good: bool
    evidence_complete: bool
    boot_state_coherent: bool
    eligible: bool
    rejection_reasons: tuple[str, ...]
    verification_status: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecoveryGenerationReport:
    schema_version: int
    current_platform: Mapping[str, Any]
    generations: tuple[RecoveryGeneration, ...]
    selected_generation_id: str | None
    certified_system_restore_plannable: bool
    planning_facts: Mapping[str, Any]
    native_restore_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "current_platform": dict(self.current_platform),
            "generations": [item.as_dict() for item in self.generations],
            "selected_generation_id": self.selected_generation_id,
            "certified_system_restore_plannable": self.certified_system_restore_plannable,
            "native_restore_enabled": self.native_restore_enabled,
            "planning_facts": dict(self.planning_facts),
        }


def generation_identity(filesystem_uuid: str | None, config_name: str, snapshot_id: int) -> str | None:
    """Return deterministic G3 identity or None when stable identity evidence is missing."""
    if not filesystem_uuid or not config_name or snapshot_id <= 0:
        return None
    canonical = f"maho-g3-v1\0{filesystem_uuid.lower()}\0{config_name}\0{snapshot_id}".encode()
    return "g3-" + hashlib.sha256(canonical).hexdigest()[:24]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _package_relation(snapshot: SnapshotEvidence) -> tuple[bool, str | None]:
    """Validate pre/post linkage when Snapper says the snapshot is transactional.

    snap-pac uses pre/post Snapper snapshots.  A single snapshot can still be a
    valid manually-created recovery state, so package linkage is not invented
    when it is not present.
    """
    stype = snapshot.snapshot_type
    if stype == "post" and not snapshot.pre_number:
        return False, "package_transaction_link_missing"
    if stype in {"pre", "post"} and snapshot.package_transaction == "broken":
        return False, "package_transaction_link_contradictory"
    return True, None


def evaluate_generation(
    *,
    snapshot: SnapshotEvidence,
    filesystem_uuid: str | None,
    root_source: str | None,
    root_fsroot: str | None,
    root_fstype: str | None,
    snapper_subvolume: str | None,
    home_scope: str,
    boot: BootEvidence,
    current_snapshot_id: int | None,
    lts_kernel_present: bool,
    expected_kernel_packages: Iterable[str],
    boot_state_transaction_required: bool,
    known_good: bool = False,
) -> RecoveryGeneration:
    reasons: list[str] = []
    expected_kernels = set(expected_kernel_packages)

    if root_fstype != "btrfs":
        reasons.append("root_not_btrfs")
    if not filesystem_uuid:
        reasons.append("root_filesystem_uuid_unknown")
    if not root_source or not root_fsroot:
        reasons.append("root_subvolume_identity_unknown")
    if snapper_subvolume is None:
        reasons.append("snapper_root_config_unavailable")
    elif snapshot.subvolume and snapshot.subvolume != snapper_subvolume:
        reasons.append("snapper_subvolume_mismatch")
    if snapshot.snapshot_id <= 0:
        reasons.append("snapshot_missing")
    if not snapshot.creation_time or _parse_time(snapshot.creation_time) is None:
        reasons.append("snapshot_creation_time_invalid")
    if not snapshot.snapshot_type:
        reasons.append("snapshot_type_unknown")
    if snapshot.read_only is False:
        reasons.append("snapshot_not_read_only")
    if snapshot.active is True or (current_snapshot_id is not None and snapshot.snapshot_id == current_snapshot_id):
        reasons.append("current_failed_generation")
    if current_snapshot_id is not None and snapshot.snapshot_id > current_snapshot_id:
        reasons.append("not_earlier_than_current_generation")

    package_ok, package_reason = _package_relation(snapshot)
    if not package_ok and package_reason:
        reasons.append(package_reason)

    if boot_state_transaction_required:
        if boot.source == "unavailable" or boot.snapshot_id is None:
            reasons.append("boot_relationship_unknown")
        elif boot.snapshot_id != snapshot.snapshot_id:
            reasons.append("boot_snapshot_mismatch")
        if boot.filesystem_uuid and filesystem_uuid and boot.filesystem_uuid.lower() != filesystem_uuid.lower():
            reasons.append("boot_filesystem_mismatch")
        if not boot.kernel_package:
            reasons.append("kernel_identity_unknown")
        elif boot.kernel_package not in expected_kernels:
            reasons.append("kernel_identity_unexpected")
        if not boot.kernel_version:
            reasons.append("kernel_version_unknown")
        if not boot.kernel_path or not boot.initramfs_path:
            reasons.append("boot_artifacts_incomplete")
        if boot.artifacts_coherent is not True:
            reasons.append("kernel_initramfs_mismatch" if boot.artifacts_coherent is False else "kernel_initramfs_coherence_unknown")
        if boot.files_verified is not True:
            reasons.append("boot_files_unverified" if boot.files_verified is None else "boot_files_verification_failed")

    # Personal-data scope is intentionally not an eligibility blocker: the user
    # may still choose a recovery generation, but Maho must never claim files are
    # preserved unless home_scope == "excluded".
    if home_scope not in {"excluded", "included", "unknown"}:
        home_scope = "unknown"

    gid = generation_identity(filesystem_uuid, snapshot.config_name, snapshot.snapshot_id)
    if gid is None:
        reasons.append("stable_generation_identity_unavailable")

    # De-duplicate while preserving deterministic diagnostic order.
    reasons = list(dict.fromkeys(reasons))
    eligible = not reasons
    complete = eligible
    boot_coherent = boot.artifacts_coherent is True and boot.files_verified is True and (
        boot.snapshot_id == snapshot.snapshot_id
    )
    verification = "known-good" if eligible and known_good else "coherent" if eligible else "rejected"
    return RecoveryGeneration(
        generation_id=gid,
        snapshot=snapshot,
        root_filesystem_uuid=filesystem_uuid,
        root_source=root_source,
        root_fsroot=root_fsroot,
        home_scope=home_scope,
        boot=boot,
        lts_kernel_present=lts_kernel_present,
        known_good=known_good,
        evidence_complete=complete,
        boot_state_coherent=boot_coherent,
        eligible=eligible,
        rejection_reasons=tuple(reasons),
        verification_status=verification,
    )


def rank_generations(generations: Iterable[RecoveryGeneration]) -> tuple[RecoveryGeneration, ...]:
    """Return deterministic view: eligible/known-good first, then nearest earlier ID.

    Snapshot numbers are Snapper's monotonic identity within a config.  Time is
    only a final display-order tie breaker and is never used as proof of safety.
    """
    def key(item: RecoveryGeneration) -> tuple[int, int, int, str]:
        return (
            1 if item.eligible else 0,
            1 if item.known_good else 0,
            item.snapshot.snapshot_id,
            item.generation_id or "",
        )
    return tuple(sorted(generations, key=key, reverse=True))


def build_report(
    *,
    platform: Mapping[str, Any],
    generations: Iterable[RecoveryGeneration],
    kernel_restore_certified: bool,
) -> RecoveryGenerationReport:
    ranked = rank_generations(generations)
    selected = next((item for item in ranked if item.eligible), None)
    selected_id = selected.generation_id if selected else None
    home_excluded = bool(selected and selected.home_scope == "excluded")
    facts: dict[str, Any] = {
        "failure": {"domain": "system-userspace"},
        "availability": {
            # Legacy bridge for the current recovery policy.  It becomes true
            # only after G3 coherence validation, never from snapshot presence.
            "root_snapshot": selected is not None,
            "root_recovery_generation": selected is not None,
            "generation_id": selected_id,
            "home_excluded_from_root_snapshot": home_excluded,
            "lts_kernel": bool(platform.get("lts_kernel_present", False)),
        },
        "recovery": {
            "boot_state_coherent": bool(selected and selected.boot_state_coherent),
            "certified": bool(selected and kernel_restore_certified),
            "requires_confirmation": bool(selected),
            "automatic_allowed": False,
            "native_restore_enabled": False,
        },
    }
    return RecoveryGenerationReport(
        schema_version=1,
        current_platform=platform,
        generations=ranked,
        selected_generation_id=selected_id,
        certified_system_restore_plannable=bool(selected and kernel_restore_certified),
        planning_facts=facts,
        native_restore_enabled=False,
    )


def report_json(report: RecoveryGenerationReport) -> str:
    return json.dumps(report.as_dict(), sort_keys=True, separators=(",", ":"))
