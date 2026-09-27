#!/usr/bin/env python3
from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_installer_plan import (  # noqa: E402
    ESP_SIZE_BYTES,
    GIB,
    MINIMUM_DISK_BYTES,
    build_install_plan,
    disk_from_lsblk_payload,
    probe_disk,
    runtime_source_revision,
    validate_destructive_confirmation,
    validate_plan_integrity,
)

REV = "a" * 40


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print("PASS", name)


def rejected(label: str, function) -> None:
    try:
        function()
    except (ValueError, RuntimeError):
        print("PASS", label)
        return
    raise AssertionError(label)


def disk(*, size: int = MINIMUM_DISK_BYTES, logical: int = 512, physical: int = 4096) -> dict:
    return {
        "path": "/dev/vdz",
        "type": "disk",
        "size": size,
        "ro": 0,
        "rm": 0,
        "model": "QEMU HARDDISK",
        "serial": "MAHO-DISPOSABLE-0001",
        "wwn": "",
        "tran": "virtio",
        "back-file": "",
        "log-sec": logical,
        "phy-sec": physical,
        "maj:min": "252:99",
        "mountpoints": [None],
        "pttype": None,
        "fstype": None,
    }


def main() -> None:
    first = build_install_plan(disk(), source_revision=REV)
    second = build_install_plan(copy.deepcopy(disk()), source_revision=REV)
    check("exact disk plan is deterministic", first == second)
    check("128 GiB whole disk reaches confirmation", first["ready_for_destructive_confirmation"] is True)
    check("plan digest and exact confirmation agree", first["destructive_confirmation"] == "ERASE-MAHO:" + first["plan_sha256"])
    check("plan ID is the digest identity", first["plan_id"] == "install-plan-" + first["plan_sha256"])
    check("plan integrity independently recomputes", validate_plan_integrity(first)["plan_id"] == first["plan_id"])

    geometry = first["geometry"]
    check("logical and physical geometry is exact", geometry["logical_sector_size_bytes"] == 512 and geometry["physical_sector_size_bytes"] == 4096)
    check("GPT headers and arrays are exact", geometry["gpt"] == {
        "entry_count": 128,
        "entry_size_bytes": 128,
        "partition_array_sectors": 32,
        "primary_header_lba": 1,
        "primary_entries_first_lba": 2,
        "backup_entries_first_lba": 268435423,
        "backup_header_lba": 268435455,
        "first_usable_lba": 34,
        "last_usable_lba": 268435422,
    })
    check("ESP starts aligned and is exactly 4 GiB", geometry["esp_first_lba"] == 2048 and geometry["esp_last_lba"] == 8390655 and geometry["esp_sector_count"] * 512 == ESP_SIZE_BYTES)
    check("LUKS consumes remaining GPT usable sectors", geometry["luks_first_lba"] == 8390656 and geometry["luks_last_lba"] == geometry["gpt"]["last_usable_lba"])

    layout = first["layout_contract"]
    check("UEFI/GPT and zram-only policy are frozen", layout["firmware"] == "uefi" and layout["partition_table"] == "gpt" and layout["swap"] == "zram-only" and layout["hibernation"] is False)
    check("ESP filesystem and mount are exact", layout["partitions"][0]["filesystem"] == "fat32" and layout["partitions"][0]["mountpoint"] == "/boot")
    check("encrypted root is LUKS2 containing Btrfs", layout["partitions"][1]["container"] == "luks2" and layout["partitions"][1]["filesystem_inside"] == "btrfs")
    check("exact Btrfs subvolume set is frozen", layout["btrfs"]["subvolumes"] == ["@", "@home", "@snapshots", "@var_log"])
    check("installation and filesystem identities are bound", all(first["installation_identity"].values()))
    check("encryption parameters are exact", first["encryption_contract"] | {} == {
        "format": "luks2", "cipher": "aes-xts-plain64", "key_size_bits": 512,
        "pbkdf": "argon2id", "sector_size_bytes": 512,
        "mapper_name": first["encryption_contract"]["mapper_name"],
        "key_delivery": "root-readable-file-mode-0600",
    })
    space = first["space_policy"]
    check("128 GiB plan keeps the 20 GiB reserve floor", space["reserve_required_bytes"] == 20 * GIB and space["reserve_valid"] is True)
    large = build_install_plan(disk(size=2 * 1024 * GIB), source_revision=REV)
    check("large-disk reserve uses 15 percent", large["space_policy"]["reserve_required_bytes"] > 20 * GIB)
    check("worst-case staging cannot consume the reserve", space["reserve_after_worst_case_staging_bytes"] >= space["reserve_required_bytes"])

    four_k = build_install_plan(disk(logical=4096, physical=4096), source_revision=REV)
    check("4Kn geometry has exact GPT boundaries", four_k["geometry"]["gpt"]["first_usable_lba"] == 6 and four_k["geometry"]["esp_first_lba"] == 256)
    undersized = build_install_plan(disk(size=MINIMUM_DISK_BYTES - 512), source_revision=REV)
    check("one-sector-below-minimum disk is blocked", "target_below_128_gib_minimum" in undersized["blockers"] and undersized["destructive_confirmation"] is None)

    changed = disk()
    changed["maj:min"] = "252:100"
    rejected("changed major:minor invalidates confirmation", lambda: validate_destructive_confirmation(first, changed, source_revision=REV, confirmation=first["destructive_confirmation"]))
    changed = disk()
    changed["serial"] = "MAHO-DISPOSABLE-0002"
    rejected("changed serial invalidates confirmation", lambda: validate_destructive_confirmation(first, changed, source_revision=REV, confirmation=first["destructive_confirmation"]))
    rejected("wrong confirmation is rejected", lambda: validate_destructive_confirmation(first, disk(), source_revision=REV, confirmation="ERASE-MAHO:" + "0" * 64))
    rejected("source revision drift is rejected", lambda: validate_destructive_confirmation(first, disk(), source_revision="b" * 40, confirmation=first["destructive_confirmation"]))

    tampered = copy.deepcopy(first)
    tampered["geometry"]["esp_last_lba"] += 1
    rejected("plan content tampering breaks digest", lambda: validate_plan_integrity(tampered))
    mounted = disk()
    mounted["mountpoints"] = ["/"]
    check("live root target is blocked", "target_or_child_mounted" in build_install_plan(mounted, source_revision=REV)["blockers"])
    removable = disk()
    removable["rm"] = 1
    check("removable target is blocked", "target_removable" in build_install_plan(removable, source_revision=REV)["blockers"])
    readonly = disk()
    readonly["ro"] = 1
    check("read-only target is blocked", "target_read_only" in build_install_plan(readonly, source_revision=REV)["blockers"])
    nonblank = disk()
    nonblank["pttype"] = "gpt"
    nonblank["children"] = [{"path": "/dev/vdz1", "type": "part", "mountpoints": [None]}]
    check("nonblank disk is blocked", "target_not_blank" in build_install_plan(nonblank, source_revision=REV)["blockers"])
    weak = disk()
    weak["serial"] = ""
    check("ambiguous physical identity is blocked", "target_identity_not_stable" in build_install_plan(weak, source_revision=REV)["blockers"])
    rejected("slash cannot be a disk path", lambda: build_install_plan(disk() | {"path": "/"}, source_revision=REV))

    payload = {"blockdevices": [disk()]}
    check("lsblk parser binds one exact path", disk_from_lsblk_payload(payload, expected_path="/dev/vdz")["serial"] == "MAHO-DISPOSABLE-0001")
    rejected("lsblk path drift is rejected", lambda: disk_from_lsblk_payload(payload, expected_path="/dev/vda"))

    class Result:
        returncode = 0
        stderr = ""
        stdout = __import__("json").dumps(payload)

    commands = []
    def fake_run(command, **kwargs):
        commands.append(tuple(command))
        return Result()

    check("live probe is read-only and exact", probe_disk("/dev/vdz", run=fake_run)["path"] == "/dev/vdz" and commands[0][0] == "lsblk" and commands[0][-1] == "/dev/vdz")

    source_root = ROOT / ".tmp-installer-source-fixture"
    try:
        (source_root / "share/maho").mkdir(parents=True, exist_ok=True)
        (source_root / "share/maho/runtime-source-revision").write_text(REV + "\n", encoding="utf-8")
        check("source revision comes from immutable metadata", runtime_source_revision(source_root) == REV)
        (source_root / "share/maho/runtime-source-revision").unlink()
        (source_root / "share/maho/release.json").write_text('{"source_revision":"' + REV + '"}\n', encoding="utf-8")
        check("packaged fallback uses signed release metadata", runtime_source_revision(source_root) == REV)
    finally:
        import shutil
        shutil.rmtree(source_root, ignore_errors=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        packaged_root = tmp_path / "payload"
        (packaged_root / "bin").mkdir(parents=True)
        (packaged_root / "lib").mkdir(parents=True)
        (packaged_root / "lib/bytecode_probe.py").write_text("VALUE = 1\n", encoding="utf-8")
        (packaged_root / "bin/maho-installer").write_text("import os,sys\nsys.path.insert(0,os.path.join(os.environ['MAHO_ROOT'],'lib'))\nimport bytecode_probe\n", encoding="utf-8")
        env = os.environ.copy()
        env["HOME"] = str(tmp_path / "home")
        env["XDG_DATA_HOME"] = str(tmp_path / "data")
        env["MAHO_PACKAGED_ROOT"] = str(packaged_root)
        subprocess.run(["bash", str(ROOT / "packaging/arch/maho-installer-wrapper"), "--help"], env=env, check=True)
        check("packaged wrapper keeps payload bytecode-free", not any(packaged_root.rglob("__pycache__")))

    print("ALL MAHO INSTALLER PLAN CONTRACTS PASS")


if __name__ == "__main__":
    main()
