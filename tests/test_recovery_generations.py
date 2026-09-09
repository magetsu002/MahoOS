#!/usr/bin/env python3
from __future__ import annotations

import copy
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
        "read-only": True,
    }


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
            "kernelPath": f"boot():/{MID}/limine_history/vmlinuz-{package}_sha256_deadbeef",
            "initramfsPath": f"boot():/{MID}/limine_history/initramfs-{package}_sha256_cafebabe",
            "filesVerified": True,
            "artifactsCoherent": True,
        }],
    }


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

    files: dict[str, Any] = {
        "/etc/machine-id": MID + "\n",
        "/etc/default/limine": f"ESP_PATH=/boot\nSNAPPER_CONFIG_NAME={spec.get('snapper_config_name', 'root')}\n",
        MANIFEST_PATH: {"filesystemUuid": FSUUID, "snapshotEntries": entries},
    }
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
    missing_limine, _ = discover("missing-limine-relationship")
    check("missing Limine relationship is rejected", not candidate(missing_limine, 20).eligible and "boot_relationship_unknown" in candidate(missing_limine, 20).rejection_reasons)
    boot_mismatch, _ = discover("mismatched-boot-state")
    check("mismatched boot state is rejected", not candidate(boot_mismatch, 20).eligible and "kernel_initramfs_mismatch" in candidate(boot_mismatch, 20).rejection_reasons)
    kernel_mismatch, _ = discover("kernel-mismatch")
    check("kernel mismatch is rejected", not candidate(kernel_mismatch, 20).eligible and "kernel_identity_unexpected" in candidate(kernel_mismatch, 20).rejection_reasons)
    no_lts, _ = discover("no-lts")
    check("LTS absence is represented without fabrication", no_lts.current_platform["lts_kernel_present"] is False)
    check("coherent primary-kernel generation does not require installed LTS", candidate(no_lts, 20).eligible)
    home_included, _ = discover("home-included")
    check("included home is never reported preserved", candidate(home_included, 20).home_scope == "included" and home_included.planning_facts["availability"]["home_excluded_from_root_snapshot"] is False)
    home_unknown, _ = discover("home-unknown")
    check("unknown home scope is never reported preserved", candidate(home_unknown, 20).home_scope == "unknown" and home_unknown.planning_facts["availability"]["home_excluded_from_root_snapshot"] is False)
    malformed, _ = discover("malformed-tool-output")
    check("malformed structured tool output fails closed", malformed.selected_generation_id is None)
    missing_cmds, missing_probe = discover("missing-commands")
    check("missing platform commands produce unavailable state", missing_cmds.selected_generation_id is None and missing_cmds.current_platform["snapper_present"] is False)
    pkg_broken, _ = discover("broken-package-link")
    check("contradictory package transaction linkage fails closed", not candidate(pkg_broken, 20).eligible and "package_transaction_link_contradictory" in candidate(pkg_broken, 20).rejection_reasons)

    all_commands = healthy_probe.commands + missing_probe.commands
    forbidden = ("rollback", "create", "delete", "remove", "set-default", "install", "-S", "-R")
    check("fixture discovery executed no mutation commands", not any(any(token in part for token in forbidden for part in cmd) for cmd in all_commands))
    refused = False
    try:
        SystemProbe().run(("snapper", "--config", "root", "rollback", "20"))
    except RuntimeError:
        refused = True
    check("system adapter refuses snapshot mutation commands", refused)

    forward = [candidate(healthy, 10), candidate(healthy, 20), candidate(healthy, 30)]
    check("deterministic ranked view is input-order independent", [x.generation_id for x in rank_generations(forward)] == [x.generation_id for x in rank_generations(reversed(forward))])
    check("G3 never grants autonomous system mutation", healthy.planning_facts["recovery"]["automatic_allowed"] is False)

    print("ALL G3 RECOVERY GENERATION CONTRACTS PASS")


if __name__ == "__main__":
    main()
