#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_recovery_discovery import FixtureProbe, SystemProbe, discover_recovery_generations  # noqa: E402
from maho_recovery_generation import generation_identity, rank_generations  # noqa: E402

SCENARIOS = json.loads((ROOT / "tests" / "fixtures" / "recovery" / "g3-platforms.json").read_text())
POLICY = json.loads((ROOT / "config" / "platform.json").read_text())
MID = "0123456789abcdef0123456789abcdef"
FSUUID = "11111111-2222-3333-4444-555555555555"
MANIFEST_PATH = f"/boot/{MID}/limine_history/snapshots.json"


def command(argv: list[str]) -> str:
    return "\0".join(argv)


def result(stdout: str = "", rc: int = 0, available: bool = True) -> dict[str, Any]:
    return {"available": available, "returncode": rc, "stdout": stdout}


def mount(target: str, source: str, fsroot: str, *, fstype: str = "btrfs") -> str:
    return json.dumps({"filesystems": [{"target": target, "source": source, "fstype": fstype, "fsroot": fsroot, "uuid": FSUUID}]})


def snapshot(number: int, *, active: bool = False) -> dict[str, Any]:
    return {
        "subvolume": "/",
        "number": number,
        "default": False,
        "active": active,
        "type": "single",
        "date": f"2026-09-0{min(number // 10, 9)}T08:00:00+00:00",
        "cleanup": "number",
        "description": f"snapshot {number}",
        "userdata": {},
    }


def artifact_content(number: int, kind: str) -> str:
    return f"g3-{kind}-artifact-{number}\n"


def artifact_digest(number: int, kind: str) -> str:
    return hashlib.sha256(artifact_content(number, kind).encode()).hexdigest()


def artifact_raw_path(number: int, kind: str) -> str:
    package = "linux-cachyos"
    prefix = "vmlinuz" if kind == "kernel" else "initramfs"
    return f"boot():/{MID}/limine_history/{prefix}-{package}_sha256_{artifact_digest(number, kind)}"


def artifact_local_path(number: int, kind: str) -> str:
    return "/boot/" + artifact_raw_path(number, kind)[len("boot():/"):]


def manifest_entry(number: int) -> dict[str, Any]:
    package = "linux-cachyos"
    return {
        "snapshotId": number,
        "entryId": f"root-{number}",
        "filesVerified": True,
        "artifactsCoherent": True,
        "kernelEntries": [{
            "package": package,
            "version": "6.17.5-1-cachyos",
            "kernelPath": artifact_raw_path(number, "kernel"),
            "initramfsPath": artifact_raw_path(number, "initramfs"),
            "filesVerified": True,
            "artifactsCoherent": True,
            "recoveryOverlayFlagged": True,
        }],
    }


def real_manifest_entry(number: int) -> dict[str, Any]:
    kernel_raw = artifact_raw_path(number, "kernel")
    init_raw = artifact_raw_path(number, "initramfs")
    def detail(key: str, raw: str, filename: str) -> dict[str, Any]:
        return {
            "limineKey": key,
            "fileName": filename,
            "fileHashName": Path(raw).name,
            "snapshotFilePathLine": raw[len("boot():"):],
            "properties": {"PATH_RESOURCE": "boot():", "HASH": ""},
        }
    return {
        "snapperID": {"snapshotID": number, "properties": {"type": "single"}},
        "kernelEntries": [{
            "kernelVersion": "Primary",
            "imageDetails": [
                detail("KERNEL_PATH", kernel_raw, "vmlinuz-linux-cachyos"),
                detail("MODULE_PATH", init_raw, "initramfs-linux-cachyos.img"),
            ],
            "cmdlineDetails": [{
                "limineKey": "KERNEL_CMDLINE",
                "snapshotCmdline": f"root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/{number}/snapshot maho.recovery_snapshot=1",
            }],
        }],
    }


def real_manifest_fixture() -> dict[str, Any]:
    fixture = build_fixture(copy.deepcopy(SCENARIOS["healthy"]))
    fixture["files"][MANIFEST_PATH] = {
        "jsonFormatVersion": "1.3.0",
        "properties": {"SNAPSHOTS_PATH": "/@snapshots", "SUBVOLUME_PATH": "/@"},
        "snapshotEntries": [real_manifest_entry(n) for n in (10, 20, 30)],
        "uuid": FSUUID,
    }
    for sid in (10, 20, 30):
        fixture["commands"][command(["pacman", "--root", f"/.snapshots/{sid}/snapshot", "-Q", "linux-cachyos"])] = result("linux-cachyos 6.17.5-1\n")
    return fixture


def build_fixture(spec: dict[str, Any]) -> dict[str, Any]:
    if spec.get("all_commands_missing"):
        return {"commands": {}, "files": {}}

    snapshots = [snapshot(10), snapshot(20), snapshot(30, active=True)]
    for sid_text, patch in spec.get("snapshot_overrides", {}).items():
        sid = int(sid_text)
        next(item for item in snapshots if item["number"] == sid).update(patch)

    entries = [manifest_entry(10), manifest_entry(20), manifest_entry(30)]
    for sid_text, patch in spec.get("manifest_overrides", {}).items():
        sid = int(sid_text)
        next(item for item in entries if item["snapshotId"] == sid).update(patch)
    for sid_text, package in spec.get("kernel_package_overrides", {}).items():
        sid = int(sid_text)
        next(item for item in entries if item["snapshotId"] == sid)["kernelEntries"][0]["package"] = package

    commands = {
        command(["findmnt", "--json", "--target", "/", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID"]): result(mount("/", "/dev/mapper/maho-root[/@]", "/@")),
        command(["findmnt", "--json", "--target", "/home", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID"]): result(mount("/home", "/dev/mapper/maho-root[/@home]", "/@home")),
        command(["pacman", "-Q", "linux-cachyos"]): result("linux-cachyos 6.17.5-1\n"),
        command(["pacman", "-Q", "linux-cachyos-lts"]): result("linux-cachyos-lts 6.12.44-1\n"),
        command(["pacman", "-Q", "snapper"]): result("snapper 0.12.1-1\n"),
        command(["pacman", "-Q", "snap-pac"]): result("snap-pac 3.0.1-1\n"),
        command(["pacman", "-Q", "limine"]): result("limine 10.0.0-1\n"),
        command(["pacman", "-Q", "limine-snapper-sync"]): result("limine-snapper-sync 1.31.0-1\n"),
        command(["snapper", "--jsonout", "--config", "root", "get-config"]): result(json.dumps({"SUBVOLUME": "/", "FSTYPE": "btrfs"})),
        command(["snapper", "--jsonout", "--config", "root", "list", "--disable-used-space"]): result(json.dumps({"root": snapshots})),
    }
    for sid in (10, 20, 30):
        commands[command(["btrfs", "property", "get", "-ts", f"/.snapshots/{sid}/snapshot", "ro"])] = result("ro=true\n")
    ro20 = command(["btrfs", "property", "get", "-ts", "/.snapshots/20/snapshot", "ro"])
    if spec.get("readonly_probe_missing"):
        commands.pop(ro20, None)
    if spec.get("readonly_probe_false"):
        commands[ro20] = result("ro=false\n")

    if spec.get("malformed_snapper_list"):
        commands[command(["snapper", "--jsonout", "--config", "root", "list", "--disable-used-space"])] = result("{broken")
    for package in spec.get("missing_packages", []):
        commands[command(["pacman", "-Q", package])] = result("", 1)

    home_scope = spec.get("home_scope", "excluded")
    home_command = command(["findmnt", "--json", "--target", "/home", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID"])
    if home_scope == "included":
        commands[home_command] = result(mount("/", "/dev/mapper/maho-root[/@]", "/@"))
    elif home_scope == "unknown":
        commands.pop(home_command)

    manifest = {"filesystemUuid": FSUUID, "snapshotEntries": entries}
    if spec.get("manifest_filesystem_uuid_missing"):
        manifest.pop("filesystemUuid")

    files: dict[str, Any] = {
        "/etc/machine-id": MID + "\n",
        "/etc/default/limine": f"ESP_PATH=/boot\nSNAPPER_CONFIG_NAME={spec.get('snapper_config_name', 'root')}\n",
        MANIFEST_PATH: manifest,
    }
    for sid in (10, 20, 30):
        files[artifact_local_path(sid, "kernel")] = artifact_content(sid, "kernel")
        files[artifact_local_path(sid, "initramfs")] = artifact_content(sid, "initramfs")
    if spec.get("corrupt_boot_artifact"):
        files[artifact_local_path(20, "kernel")] = "corrupted-kernel-artifact\n"
    if spec.get("missing_boot_artifact"):
        files.pop(artifact_local_path(20, "initramfs"), None)
    if spec.get("manifest_missing"):
        files.pop(MANIFEST_PATH)
    return {"commands": commands, "files": files}


def discover(name: str):
    probe = FixtureProbe(build_fixture(copy.deepcopy(SCENARIOS[name])))
    return discover_recovery_generations(POLICY, probe), probe


def candidate(report, snapshot_id: int):
    return next(g for g in report.generations if g.snapshot.snapshot_id == snapshot_id)


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def main() -> None:
    healthy, healthy_probe = discover("healthy")
    check("healthy Btrfs + Snapper root configuration is discovered", healthy.current_platform["root_fstype"] == "btrfs" and healthy.current_platform["snapper_config_available"])
    check("multiple snapshots are represented", len(healthy.generations) == 3)
    check("current failed generation is excluded", not candidate(healthy, 30).eligible and "current_failed_generation" in candidate(healthy, 30).rejection_reasons)
    check("valid previous candidate is eligible", candidate(healthy, 20).eligible)
    check("deterministic selection prefers nearest coherent previous generation", healthy.selected_generation_id == candidate(healthy, 20).generation_id)
    check("LTS kernel presence is exposed", healthy.current_platform["lts_kernel_present"] is True)
    check("separate home subvolume proves root-only recovery", candidate(healthy, 20).home_scope == "excluded" and healthy.planning_facts["availability"]["home_excluded_from_root_snapshot"] is True)
    check("current platform certification remains false", healthy.certified_system_restore_plannable is False and healthy.planning_facts["recovery"]["certified"] is False)
    check("L3 facts remain confirmation gated", healthy.planning_facts["recovery"]["requires_confirmation"] is True and healthy.planning_facts["recovery"]["automatic_allowed"] is False)
    check("live restore remains disabled", healthy.native_restore_enabled is False and healthy.planning_facts["recovery"]["native_restore_enabled"] is False)

    gid = generation_identity(FSUUID, "root", 20)
    check("generation identity is deterministic", gid == generation_identity(FSUUID, "root", 20) and gid is not None)
    check("generation identity ignores display metadata", gid == candidate(healthy, 20).generation_id)
    check("generation identity is filesystem scoped", gid != generation_identity("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "root", 20))

    no_snapper, _ = discover("no-snapper")
    check("no Snapper fails closed", not no_snapper.generations and no_snapper.selected_generation_id is None)
    wrong, _ = discover("wrong-snapper-config")
    check("wrong Snapper config fails closed", wrong.current_platform["snapper_config_mismatch"] is True and wrong.selected_generation_id is None)
    incomplete, _ = discover("incomplete-snapshot")
    check("incomplete snapshot metadata is rejected", not candidate(incomplete, 20).eligible and "snapshot_creation_time_invalid" in candidate(incomplete, 20).rejection_reasons)

    check(
        "Snapper JSON without read-only field is certified through Btrfs property",
        candidate(healthy, 20).snapshot.read_only is True,
    )
    unknown_ro, _ = discover("unknown-read-only")
    check("unknown snapshot read-only state is rejected", not candidate(unknown_ro, 20).eligible and "snapshot_read_only_unknown" in candidate(unknown_ro, 20).rejection_reasons)
    writable, _ = discover("writable-snapshot")
    check("writable snapshot is rejected", not candidate(writable, 20).eligible and "snapshot_not_read_only" in candidate(writable, 20).rejection_reasons)
    missing_subvolume, _ = discover("missing-snapshot-subvolume")
    check("missing snapshot subvolume identity is rejected", not candidate(missing_subvolume, 20).eligible and "snapshot_subvolume_unknown" in candidate(missing_subvolume, 20).rejection_reasons)
    unknown_type, _ = discover("unknown-snapshot-type")
    check("unknown snapshot type is rejected", not candidate(unknown_type, 20).eligible and "snapshot_type_unknown" in candidate(unknown_type, 20).rejection_reasons)

    missing_limine, _ = discover("missing-limine-relationship")
    check("missing Limine relationship is rejected", not candidate(missing_limine, 20).eligible and "boot_relationship_unknown" in candidate(missing_limine, 20).rejection_reasons)
    missing_boot_fs, _ = discover("missing-boot-filesystem-identity")
    check("missing boot filesystem identity is rejected", not candidate(missing_boot_fs, 20).eligible and "boot_filesystem_identity_unknown" in candidate(missing_boot_fs, 20).rejection_reasons)
    boot20 = candidate(healthy, 20).boot
    check(
        "saved boot artifacts are independently SHA-256 verified",
        boot20.files_verified is True
        and boot20.kernel_sha256_expected == boot20.kernel_sha256_observed
        and boot20.initramfs_sha256_expected == boot20.initramfs_sha256_observed,
    )

    real_probe = FixtureProbe(real_manifest_fixture())
    real_report = discover_recovery_generations(POLICY, real_probe)
    real20 = candidate(real_report, 20)
    check(
        "real limine-snapper-sync 1.31 nested manifest is fully verified",
        real20.eligible
        and real20.boot.snapshot_id == 20
        and real20.boot.filesystem_uuid == FSUUID
        and real20.boot.kernel_package == "linux-cachyos"
        and real20.boot.kernel_version == "6.17.5-1"
        and real20.boot.files_verified is True
        and real20.boot.artifacts_coherent is True,
    )
    real_no_overlay_fixture = real_manifest_fixture()
    real_no_overlay_fixture["files"][MANIFEST_PATH]["snapshotEntries"][1]["kernelEntries"][0]["cmdlineDetails"][0]["snapshotCmdline"] = f"root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/20/snapshot"
    real_no_overlay = candidate(discover_recovery_generations(POLICY, FixtureProbe(real_no_overlay_fixture)), 20)
    check(
        "real nested manifest without Maho recovery overlay flag is rejected",
        not real_no_overlay.eligible
        and "recovery_overlay_flag_missing" in real_no_overlay.rejection_reasons
        and real_no_overlay.boot.recovery_overlay_flagged is False,
    )

    real_bad_fixture = real_manifest_fixture()
    real_bad_fixture["files"][artifact_local_path(20, "kernel")] = "corrupted-real-kernel\n"
    real_bad = candidate(discover_recovery_generations(POLICY, FixtureProbe(real_bad_fixture)), 20)
    check("real nested manifest still rejects corrupt saved kernel", not real_bad.eligible and "boot_files_verification_failed" in real_bad.rejection_reasons)
    real_wrong_root_fixture = real_manifest_fixture()
    real_wrong_root_fixture["files"][MANIFEST_PATH]["snapshotEntries"][1]["kernelEntries"][0]["cmdlineDetails"][0]["snapshotCmdline"] = f"root=UUID={FSUUID} rw rootflags=subvol=/@snapshots/999/snapshot"
    real_wrong_root = candidate(discover_recovery_generations(POLICY, FixtureProbe(real_wrong_root_fixture)), 20)
    check("real nested manifest requires exact snapshot root cmdline", not real_wrong_root.eligible and "kernel_initramfs_mismatch" in real_wrong_root.rejection_reasons)
    corrupt_boot, _ = discover("corrupt-boot-artifact")
    check("corrupt saved boot artifact is rejected", not candidate(corrupt_boot, 20).eligible and "boot_files_verification_failed" in candidate(corrupt_boot, 20).rejection_reasons)
    missing_boot, _ = discover("missing-boot-artifact")
    check("missing saved boot artifact is rejected", not candidate(missing_boot, 20).eligible and "boot_files_verification_failed" in candidate(missing_boot, 20).rejection_reasons)
    boot_mismatch, _ = discover("mismatched-boot-state")
    check("mismatched boot state is rejected", not candidate(boot_mismatch, 20).eligible and "kernel_initramfs_mismatch" in candidate(boot_mismatch, 20).rejection_reasons)
    kernel_mismatch, _ = discover("kernel-mismatch")
    check("kernel mismatch is rejected", not candidate(kernel_mismatch, 20).eligible and "kernel_identity_unexpected" in candidate(kernel_mismatch, 20).rejection_reasons)
    no_lts, _ = discover("no-lts")
    check("LTS absence is represented without fabrication", no_lts.current_platform["lts_kernel_present"] is False)
    check("coherent primary-kernel generation does not require installed LTS", candidate(no_lts, 20).eligible)

    home_included, _ = discover("home-included")
    check("included home is explicit and never reported preserved", candidate(home_included, 20).eligible and candidate(home_included, 20).home_scope == "included" and home_included.planning_facts["availability"]["home_excluded_from_root_snapshot"] is False)
    home_unknown, _ = discover("home-unknown")
    check("unknown home scope fails closed", not candidate(home_unknown, 20).eligible and "personal_data_scope_unknown" in candidate(home_unknown, 20).rejection_reasons and home_unknown.selected_generation_id is None)

    older_marked_good, _ = discover("known-good-older")
    check("metadata known-good marker cannot outrank nearer eligible generation", older_marked_good.selected_generation_id == candidate(older_marked_good, 20).generation_id)

    malformed, _ = discover("malformed-tool-output")
    check("malformed structured tool output fails closed", malformed.selected_generation_id is None)
    missing_cmds, missing_probe = discover("missing-commands")
    check("missing platform commands produce unavailable state", missing_cmds.selected_generation_id is None and missing_cmds.current_platform["snapper_present"] is False)
    pkg_broken, _ = discover("broken-package-link")
    check("contradictory package transaction linkage fails closed", not candidate(pkg_broken, 20).eligible and "package_transaction_link_contradictory" in candidate(pkg_broken, 20).rejection_reasons)

    all_commands = healthy_probe.commands + missing_probe.commands
    forbidden = ("rollback", "create", "delete", "remove", "set-default", "install", "-S", "-R")
    check("fixture discovery executed no mutation commands", not any(any(token in part for token in forbidden for part in cmd) for cmd in all_commands))

    refused_shapes = (
        ("snapper", "--config", "root", "rollback", "20"),
        ("snapper", "--config", "root", "rollback", "list"),
        ("snapper", "--jsonout", "--config", "root", "list", "rollback"),
        ("pacman", "-Q", "snapper", "-S"),
        ("pacman", "--root", "/", "-Q", "linux-cachyos"),
        ("pacman", "--root", "/.snapshots/20/snapshot", "-S", "linux-cachyos"),
        ("btrfs", "property", "set", "-ts", "/.snapshots/20/snapshot", "ro", "false"),
        ("btrfs", "property", "get", "-ts", "/etc/passwd", "ro"),
    )
    for argv in refused_shapes:
        refused = False
        try:
            SystemProbe().run(argv)
        except RuntimeError:
            refused = True
        check(f"system adapter refuses unsafe command shape {argv!r}", refused)

    forward = [candidate(healthy, 10), candidate(healthy, 20), candidate(healthy, 30)]
    check("deterministic ranked view is input-order independent", [x.generation_id for x in rank_generations(forward)] == [x.generation_id for x in rank_generations(reversed(forward))])
    check("G3 never grants autonomous system mutation", healthy.planning_facts["recovery"]["automatic_allowed"] is False)

    print("ALL G3 RECOVERY GENERATION CONTRACTS PASS")


if __name__ == "__main__":
    main()
