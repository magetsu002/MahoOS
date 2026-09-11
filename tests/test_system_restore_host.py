#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_system_restore_host import (  # noqa: E402
    HostCommandResult,
    SystemHostBackend,
    SystemPreparationOps,
)

MID = "0123456789abcdef0123456789abcdef"
TX = "l3-20260911T120000Z-deadbeef"
SID = 400
BOOT = "/boot-test"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")

def hashed(name: str, data: bytes) -> tuple[dict, str, bytes]:
    digest = hashlib.sha256(data).hexdigest()
    hash_name = f"{name}_sha256_{digest}"
    return ({"fileName": name, "fileHashName": hash_name}, hash_name, data)


def kernel_entry(package: str, snapshot_id: int, *, flagged: bool = True):
    if package == "linux-cachyos":
        kernel_name = "vmlinuz-linux-cachyos"
        initramfs_name = "initramfs-linux-cachyos.img"
        label = "Primary"
    else:
        kernel_name = "vmlinuz-linux-cachyos-lts"
        initramfs_name = "initramfs-linux-cachyos-lts.img"
        label = "Fallback (LTS)"
    k, kh, kd = hashed(kernel_name, (kernel_name + "-bytes").encode())
    i, ih, idata = hashed(initramfs_name, (initramfs_name + "-bytes").encode())
    k["limineKey"] = "KERNEL_PATH"
    i["limineKey"] = "MODULE_PATH"
    cmd = f"root=UUID=root rw rootflags=subvol=/@snapshots/{snapshot_id}/snapshot"
    if flagged:
        cmd += " maho.recovery_snapshot=1"
    entry = {
        "kernelVersion": label,
        "imageDetails": [k, i],
        "cmdlineDetails": [{"snapshotCmdline": cmd}],
    }
    return entry, {kh: kd, ih: idata}

def manifest(*, include_fallback: bool = True, fallback_flagged: bool = True):
    primary, files = kernel_entry("linux-cachyos", SID)
    kernels = [primary]
    if include_fallback:
        fallback, extra = kernel_entry("linux-cachyos-lts", SID, flagged=fallback_flagged)
        kernels.append(fallback)
        files.update(extra)
    payload = {
        "snapshotEntries": [{
            "snapperID": {"snapshotID": SID},
            "kernelEntries": kernels,
        }]
    }
    return json.dumps(payload), files


class FakeBackend:
    def __init__(self, *, manifest_text: str, artifacts: dict[str, bytes], root: bool = True):
        self.manifest_text = manifest_text
        self.artifacts = dict(artifacts)
        self.root = root
        self.commands: list[tuple[str, ...]] = []
        self.read_paths: list[str] = []
        self.snapshot_exists = True
        self.snapshot_uuid_value = "backup-snapshot-uuid"
        self.read_only_value = True

    def run(self, argv):
        args = tuple(str(item) for item in argv)
        self.commands.append(args)
        if args[:4] == ("snapper", "-c", "root", "create"):
            return HostCommandResult(0, f"{SID}\n", "")
        if args == ("btrfs", "subvolume", "show", f"/.snapshots/{SID}/snapshot"):
            return HostCommandResult(0, f"Name: snapshot\nUUID: {self.snapshot_uuid_value}\nParent UUID: parent\n", "")
        if args == ("btrfs", "property", "get", "-ts", f"/.snapshots/{SID}/snapshot", "ro"):
            value = "true" if self.read_only_value else "false"
            return HostCommandResult(0, f"ro={value}\n", "")
        if args == ("findmnt", "--json", "--target", "/home", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID"):
            payload = {"filesystems": [{
                "target": "/home", "source": "/dev/fake[/@home]",
                "fstype": "btrfs", "fsroot": "/@home", "uuid": "home-fs-uuid",
            }]}
            return HostCommandResult(0, json.dumps(payload), "")
        if args == ("btrfs", "subvolume", "show", "/home"):
            return HostCommandResult(0, "Name: @home\nUUID: home-subvolume-uuid\nParent UUID: -\n", "")
        return HostCommandResult(1, "", "unexpected command")

    def read_text(self, path: str):
        if path == f"{BOOT}/{MID}/limine_history/snapshots.json":
            return self.manifest_text
        return None

    def read_bytes(self, path: str):
        self.read_paths.append(path)
        return self.artifacts.get(Path(path).name)

    def exists(self, path: str) -> bool:
        return self.snapshot_exists and path == f"/.snapshots/{SID}/snapshot"

    def euid(self) -> int:
        return 0 if self.root else 1000


def make_ops(backend: FakeBackend) -> SystemPreparationOps:
    return SystemPreparationOps(
        machine_id=MID,
        boot_root=BOOT,
        backend=backend,
        timeout_seconds=0.0,
        poll_seconds=0.0,
    )

def main() -> None:
    text, files = manifest()
    backend = FakeBackend(manifest_text=text, artifacts=files)
    ops = make_ops(backend)

    created = ops.create_emergency_snapshot(TX)
    check("root host creates one exact emergency snapshot", created == SID)
    create_cmd = backend.commands[0]
    check("emergency snapshot is forced read-only", "--read-only" in create_cmd)
    check("emergency snapshot description is transaction-bound", f"Maho L3 emergency backup {TX}" in create_cmd)
    check("emergency snapshot userdata is transaction-bound", any(f"maho.transaction={TX}" in part for part in create_cmd))

    identity = ops.home_identity()
    check("root host binds separate home filesystem", identity["filesystem_uuid"] == "home-fs-uuid")
    check("root host binds exact home subvolume UUID", identity["subvolume_uuid"] == "home-subvolume-uuid")

    evidence = ops.wait_for_backup(SID)
    check("backup snapshot UUID is independently read", evidence["snapshot_uuid"] == "backup-snapshot-uuid")
    check("backup remains read-only", evidence["read_only"] is True)
    check("both Primary and Fallback are required", set(evidence["kernel_packages"]) == {"linux-cachyos", "linux-cachyos-lts"})
    check("saved boot artifacts are hash verified", evidence["files_verified"] is True)
    check("backup recovery cmdlines are exact", evidence["recovery_overlay_flagged"] is True)
    check("complete backup boot state is coherent", evidence["boot_state_coherent"] is True)

    corrupt_text, corrupt_files = manifest()
    first_name = next(iter(corrupt_files))
    corrupt_files[first_name] = b"corrupt"
    corrupt = make_ops(FakeBackend(manifest_text=corrupt_text, artifacts=corrupt_files)).wait_for_backup(SID)
    check("corrupt saved artifact blocks verification", corrupt["files_verified"] is False)
    check("corrupt saved artifact blocks coherent backup", corrupt["boot_state_coherent"] is False)

    primary_only_text, primary_only_files = manifest(include_fallback=False)
    primary_only = make_ops(FakeBackend(
        manifest_text=primary_only_text, artifacts=primary_only_files
    )).wait_for_backup(SID)
    check("missing Fallback is not a coherent backup", primary_only["boot_state_coherent"] is False)
    check("missing Fallback exposes incomplete kernel set", primary_only["kernel_packages"] == ["linux-cachyos"])

    unflagged_text, unflagged_files = manifest(fallback_flagged=False)
    unflagged = make_ops(FakeBackend(
        manifest_text=unflagged_text, artifacts=unflagged_files
    )).wait_for_backup(SID)
    check("missing recovery flag blocks backup", unflagged["recovery_overlay_flagged"] is False)
    check("missing recovery flag blocks coherent boot state", unflagged["boot_state_coherent"] is False)

    nonroot = FakeBackend(manifest_text=text, artifacts=files, root=False)
    denied = False
    try:
        make_ops(nonroot).create_emergency_snapshot(TX)
    except PermissionError:
        denied = True
    check("non-root host cannot create emergency snapshot", denied and not nonroot.commands)

    allowed_create = (
        "snapper", "-c", "root", "create", "--read-only", "--print-number",
        "--description", f"Maho L3 emergency backup {TX}",
        "--userdata", f"important=yes,maho.known_good=yes,maho.restore_backup=yes,maho.transaction={TX}",
    )
    check("system host allows exact bounded create command", SystemHostBackend._allowed(allowed_create))
    check("system host refuses rollback command", not SystemHostBackend._allowed(("snapper", "-c", "root", "rollback", "349")))
    check("system host refuses writable snapshot mutation", not SystemHostBackend._allowed(("btrfs", "property", "set", "-ts", "/.snapshots/400/snapshot", "ro", "false")))
    check("system host refuses arbitrary subvolume inspection", not SystemHostBackend._allowed(("btrfs", "subvolume", "show", "/etc")))

    mismatched_tx = list(allowed_create)
    mismatched_tx[-1] = mismatched_tx[-1].replace(TX, "l3-20260911T120001Z-feedface")
    check("snapshot description and userdata must bind the same transaction", not SystemHostBackend._allowed(tuple(mismatched_tx)))

    traversal_payload = json.loads(text)
    traversal_image = traversal_payload["snapshotEntries"][0]["kernelEntries"][0]["imageDetails"][0]
    traversal_image["fileHashName"] = "../outside_sha256_" + "0" * 64
    traversal_backend = FakeBackend(manifest_text=json.dumps(traversal_payload), artifacts=files)
    traversal = make_ops(traversal_backend).wait_for_backup(SID)
    check("manifest artifact path traversal is rejected", traversal["files_verified"] is False)
    check("rejected traversal never reads outside history root", all(".." not in path for path in traversal_backend.read_paths))

    print("ALL SYSTEM RESTORE HOST CONTRACTS PASS")


if __name__ == "__main__":
    main()
