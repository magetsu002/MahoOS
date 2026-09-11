#!/usr/bin/env python3
from __future__ import annotations

import copy
from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_recovery_generation import BootEvidence, RecoveryGeneration, RecoveryGenerationReport, SnapshotEvidence  # noqa: E402
from maho_system_restore import plan_system_restore  # noqa: E402

FSUUID = "11111111-2222-3333-4444-555555555555"
GID = "g3-0123456789abcdef01234567"
KHASH = "a" * 64
IHASH = "b" * 64
POLICY = json.loads((ROOT / "config" / "platform.json").read_text())


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def generation(**changes) -> RecoveryGeneration:
    item = RecoveryGeneration(
        generation_id=GID,
        snapshot=SnapshotEvidence(
            config_name="root",
            snapshot_id=349,
            creation_time="2026-09-11T08:16:09+00:00",
            subvolume="/",
            snapshot_type="single",
            cleanup="number",
            description="known-good",
            userdata={"maho.known_good": "yes"},
            active=True,
            read_only=True,
        ),
        root_filesystem_uuid=FSUUID,
        root_source="/dev/mapper/maho-root[/@snapshots/349/snapshot]",
        root_fsroot="/@snapshots/349/snapshot",
        home_scope="excluded",
        boot=BootEvidence(
            source="limine-snapper-sync",
            entry_id="root-349",
            kernel_package="linux-cachyos",
            kernel_version="7.1.8-1-cachyos",
            kernel_path="/boot/history/vmlinuz",
            initramfs_path="/boot/history/initramfs",
            kernel_sha256_expected=KHASH,
            kernel_sha256_observed=KHASH,
            initramfs_sha256_expected=IHASH,
            initramfs_sha256_observed=IHASH,
            snapshot_id=349,
            filesystem_uuid=FSUUID,
            files_verified=True,
            artifacts_coherent=True,
            recovery_overlay_flagged=True,
        ),
        lts_kernel_present=True,
        known_good=True,
        evidence_complete=False,
        boot_state_coherent=True,
        eligible=False,
        rejection_reasons=("current_failed_generation",),
        verification_status="rejected",
    )
    return replace(item, **changes)


def report(item: RecoveryGeneration | None = None, **changes) -> RecoveryGenerationReport:
    item = item or generation()
    base = RecoveryGenerationReport(
        schema_version=1,
        current_platform={
            "root_fstype": "btrfs",
            "root_fsroot": "/@snapshots/349/snapshot",
            "root_filesystem_uuid": FSUUID,
            "recovery_overlay_active": True,
            "current_snapshot_id": 349,
            "home_scope": "excluded",
        },
        generations=(item,),
        selected_generation_id=None,
        certified_system_restore_plannable=False,
        planning_facts={},
        native_restore_enabled=False,
    )
    return replace(base, **changes)


def provider(**changes):
    base = {
        "path": "/usr/bin/limine-snapper-restore",
        "package": "limine-snapper-sync",
        "version": "1.31.0-1",
        "uid": 0,
        "mode": 0o755,
        "cmdline": f"root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/349/snapshot maho.recovery_snapshot=1",
        "config": {
            "RESTORE_METHOD": "replace",
            "ROOT_SUBVOLUME_PATH": "/@",
            "SET_SNAPSHOT_AS_DEFAULT": "no",
            "SNAPSHOT_WRITABLE": "no",
            "SNAPPER_CONFIG_NAME": "root",
            "FS_UUID": FSUUID,
        },
    }
    base.update(changes)
    return base


def main() -> None:
    ready = plan_system_restore(report(), GID, POLICY, provider())
    check("exact recovery generation is native-campaign ready", ready.campaign_ready and not ready.blockers)
    check("uncertified source never claims production restore", ready.production_enabled is False)
    check("L3 remains confirmation-gated and never automatic", ready.requires_confirmation and not ready.automatic_allowed)
    check("plan binds exact root-only scope", ready.snapshot_id == 349 and ready.root_snapshot_fsroot == "/@snapshots/349/snapshot" and ready.home_scope == "excluded")
    check("plan binds exact verified boot hashes", ready.expected_kernel_sha256 == KHASH and ready.expected_initramfs_sha256 == IHASH)

    no_overlay = report()
    no_overlay = replace(no_overlay, current_platform={**no_overlay.current_platform, "recovery_overlay_active": False})
    check("normal boot cannot become restore campaign", "recovery_overlay_not_active" in plan_system_restore(no_overlay, GID, POLICY, provider()).blockers)

    wrong_current = report()
    wrong_current = replace(wrong_current, current_platform={**wrong_current.current_platform, "current_snapshot_id": 348})
    check("requested generation must be the booted recovery generation", "requested_generation_not_current" in plan_system_restore(wrong_current, GID, POLICY, provider()).blockers)

    extra_rejection = generation(rejection_reasons=("current_failed_generation", "boot_files_verification_failed"))
    check("all non-current generation rejections fail closed", "generation_has_unresolved_rejections" in plan_system_restore(report(extra_rejection), GID, POLICY, provider()).blockers)
    check("included home scope blocks root restore", "personal_data_scope_not_excluded" in plan_system_restore(report(generation(home_scope="included")), GID, POLICY, provider()).blockers)
    check("known-good marker is required", "generation_not_known_good" in plan_system_restore(report(generation(known_good=False)), GID, POLICY, provider()).blockers)

    check("provider version is pinned for V1 certification", "provider_version_uncertified" in plan_system_restore(report(), GID, POLICY, provider(version="1.32.0-1")).blockers)
    check("provider command path is exact", "provider_command_mismatch" in plan_system_restore(report(), GID, POLICY, provider(path="/tmp/restore")).blockers)
    check("provider must be root-owned", "provider_not_root_owned" in plan_system_restore(report(), GID, POLICY, provider(uid=1000)).blockers)
    check("provider cannot be group/world writable", "provider_permissions_unsafe" in plan_system_restore(report(), GID, POLICY, provider(mode=0o775)).blockers)

    bad_config = provider()
    bad_config["config"] = {**bad_config["config"], "RESTORE_METHOD": "rsync"}
    check("restore method drift blocks L3", "provider_config_restore_method_mismatch" in plan_system_restore(report(), GID, POLICY, bad_config).blockers)
    missing_flag = provider(cmdline=f"root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/349/snapshot")
    check("kernel recovery flag is mandatory", "kernel_recovery_flag_missing" in plan_system_restore(report(), GID, POLICY, missing_flag).blockers)
    wrong_root = provider(cmdline=f"root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/348/snapshot maho.recovery_snapshot=1")
    check("kernel snapshot root must match target", "kernel_snapshot_root_mismatch" in plan_system_restore(report(), GID, POLICY, wrong_root).blockers)

    bad_hash_boot = replace(generation().boot, kernel_sha256_observed="c" * 64)
    bad_hash_generation = generation(boot=bad_hash_boot)
    check("unverified kernel hash blocks restore", "kernel_hash_not_verified" in plan_system_restore(report(bad_hash_generation), GID, POLICY, provider()).blockers)

    certified_policy = copy.deepcopy(POLICY)
    certified_policy["boot"]["kernel_update_snapshot_restore_certified"] = True
    certified_report = report(certified_system_restore_plannable=True, native_restore_enabled=True)
    check("production enablement requires every certification gate", plan_system_restore(certified_report, GID, certified_policy, provider()).production_enabled is True)

    try:
        plan_system_restore(report(), "g3-does-not-exist", POLICY, provider())
    except ValueError:
        pass
    else:
        raise AssertionError("unknown recovery generation must fail closed")
    print("PASS unknown recovery generation fails closed")
    print("ALL SYSTEM RESTORE PREFLIGHT CONTRACTS PASS")


if __name__ == "__main__":
    main()
