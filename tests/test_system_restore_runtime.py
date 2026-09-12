#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from maho_system_restore_journal import create_journal, transition_journal  # noqa: E402
from maho_system_restore_runtime import (  # noqa: E402
    RuntimeCommandResult,
    SystemRestoreRuntimeOps,
    SystemRuntimeBackend,
)
from maho_system_restore_transaction import postboot_blockers  # noqa: E402

TX = "l3-20260911T120000Z-deadbeef"
MID = "0123456789abcdef0123456789abcdef"
FSUUID = "ce979d1c-c145-4be0-9ce3-591b6fd0a3a1"
TARGET_UUID = "target-snapshot-uuid"
BACKUP_UUID = "backup-snapshot-uuid"
HOME_UUID = "home-subvolume-uuid"
KERNEL = b"target-kernel"
INITRAMFS = b"target-initramfs"
KHASH = hashlib.sha256(KERNEL).hexdigest()
IHASH = hashlib.sha256(INITRAMFS).hexdigest()


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def journal() -> dict:
    data = create_journal(
        transaction_id=TX,
        source_revision="a" * 40,
        target={
            "generation_id": "g3-0123456789abcdef01234567",
            "snapshot_id": 349,
            "snapshot_uuid": TARGET_UUID,
            "root_filesystem_uuid": FSUUID,
            "expected_kernel_package": "linux-cachyos",
            "expected_kernel_version": "7.1.8-1",
            "expected_kernel_sha256": KHASH,
            "expected_initramfs_sha256": IHASH,
        },
        backup={"snapshot_id": 400, "snapshot_uuid": BACKUP_UUID},
        home={
            "filesystem_uuid": FSUUID,
            "fsroot": "/@home",
            "subvolume_uuid": HOME_UUID,
        },
        provider={
            "command": "/usr/bin/limine-snapper-restore",
            "package": "limine-snapper-sync",
            "version": "1.31.0-1",
        },
    )
    data = transition_journal(data, "restore-started")
    data = transition_journal(data, "provider-returned")
    return transition_journal(data, "restored-awaiting-reboot")



class FakePrep:
    def home_identity(self):
        return {"filesystem_uuid": FSUUID, "fsroot": "/@home", "subvolume_uuid": HOME_UUID}

    def wait_for_backup(self, snapshot_id: int):
        assert snapshot_id == 400
        return {"snapshot_uuid": BACKUP_UUID, "read_only": True}


class FakeRuntime:
    def __init__(self, *, root: bool = True, running_kernel: bytes = KERNEL, fail_show: bool = False):
        self.root = root
        self.running_kernel = running_kernel
        self.fail_show = fail_show
        self.commands: list[tuple[str, ...]] = []
        self.dirs: set[str] = set()

    def run(self, argv):
        args = tuple(str(x) for x in argv)
        self.commands.append(args)
        mountpoint = f"/run/maho-l3/{TX}"
        if args[:3] == ("findmnt", "--json", "--target"):
            target = args[3]
            row = {"target": target, "source": "/dev/fake", "fstype": "btrfs", "uuid": FSUUID}
            row["fsroot"] = "/@" if target == "/" else "/@home"
            return RuntimeCommandResult(0, json.dumps({"filesystems": [row]}))
        if args == ("mount", "-t", "btrfs", "-o", "ro,subvolid=5", f"UUID={FSUUID}", mountpoint):
            return RuntimeCommandResult(0, "")
        if args == ("btrfs", "subvolume", "show", f"{mountpoint}/@"):
            if self.fail_show:
                return RuntimeCommandResult(1, "", "synthetic")
            return RuntimeCommandResult(0, f"UUID: new-root\nParent UUID: {TARGET_UUID}\n")
        if args == ("btrfs", "subvolume", "show", "/"):
            return RuntimeCommandResult(0, f"UUID: new-root\nParent UUID: {TARGET_UUID}\n")
        if args == ("umount", mountpoint):
            return RuntimeCommandResult(0, "")
        if args == ("pacman", "-Q", "linux-cachyos"):
            return RuntimeCommandResult(0, "linux-cachyos 7.1.8-1\n")
        if args == ("uname", "-r"):
            return RuntimeCommandResult(0, "7.1.8-1-cachyos\n")
        return RuntimeCommandResult(1, "", "unexpected")

    def read_text(self, path: str):
        if path == "/proc/cmdline":
            return f"root=UUID={FSUUID} rw rootflags=subvol=@"
        if path == "/usr/lib/modules/7.1.8-1-cachyos/pkgbase":
            return "linux-cachyos\n"
        return None

    def read_bytes(self, path: str):
        if path == "/boot/vmlinuz-linux-cachyos":
            return KERNEL
        if path == "/boot/initramfs-linux-cachyos.img":
            return INITRAMFS
        if path == "/usr/lib/modules/7.1.8-1-cachyos/vmlinuz":
            return self.running_kernel
        return None

    def mkdir(self, path: str) -> None:
        if path in self.dirs:
            raise FileExistsError(path)
        self.dirs.add(path)

    def rmdir(self, path: str) -> None:
        self.dirs.remove(path)

    def euid(self) -> int:
        return 0 if self.root else 1000


def ops(backend: FakeRuntime) -> SystemRestoreRuntimeOps:
    return SystemRestoreRuntimeOps(
        journal(), machine_id=MID, transaction_id=TX,
        backend=backend, preparation_ops=FakePrep(),
    )


def main() -> None:
    backend = FakeRuntime()
    structural = ops(backend).structural_evidence()
    check("pre-reboot structural proof binds target parent", structural.root_parent_uuid == TARGET_UUID)
    check("pre-reboot structural proof binds boot hashes", structural.kernel_sha256 == KHASH and structural.initramfs_sha256 == IHASH)
    check("pre-reboot structural proof preserves home", structural.home_subvolume_uuid == HOME_UUID)
    check("verification top-level mount is read-only", ("mount", "-t", "btrfs", "-o", "ro,subvolid=5", f"UUID={FSUUID}", f"/run/maho-l3/{TX}") in backend.commands)
    check("verification mount is always unmounted", ("umount", f"/run/maho-l3/{TX}") in backend.commands and not backend.dirs)

    post = ops(FakeRuntime()).postboot_evidence()
    check("postboot package version is independently verified", post.kernel_version == "7.1.8-1")
    check("postboot running kernel package comes from module tree", post.kernel_package == "linux-cachyos")
    check("postboot running kernel release is observed", post.running_kernel_version == "7.1.8-1-cachyos")
    check("postboot running kernel image is target-bound", post.running_kernel_sha256 == KHASH)
    check("postboot normal root has no recovery state", not post.recovery_overlay_active and not post.recovery_flag_present)
    check("complete postboot evidence passes transaction contract", not postboot_blockers(journal(), post))

    wrong = ops(FakeRuntime(running_kernel=b"wrong-kernel")).postboot_evidence()
    check("wrong running kernel is rejected", "running_kernel_hash_mismatch" in postboot_blockers(journal(), wrong))

    denied = False
    nonroot = FakeRuntime(root=False)
    try:
        ops(nonroot).structural_evidence()
    except PermissionError:
        denied = True
    check("non-root structural collector mutates nothing", denied and not nonroot.commands and not nonroot.dirs)

    cleanup = FakeRuntime(fail_show=True)
    failed = False
    try:
        ops(cleanup).structural_evidence()
    except RuntimeError:
        failed = True
    check("failed structural inspection still unmounts", failed and ("umount", f"/run/maho-l3/{TX}") in cleanup.commands and not cleanup.dirs)

    exact_mount = ("mount", "-t", "btrfs", "-o", "ro,subvolid=5", f"UUID={FSUUID}", f"/run/maho-l3/{TX}")
    check("runtime allows exact read-only top-level mount", SystemRuntimeBackend._allowed(exact_mount))
    check("runtime refuses writable top-level mount", not SystemRuntimeBackend._allowed(("mount", "-t", "btrfs", "-o", "rw,subvolid=5", f"UUID={FSUUID}", f"/run/maho-l3/{TX}")))
    check("runtime refuses arbitrary mountpoint", not SystemRuntimeBackend._allowed(("mount", "-t", "btrfs", "-o", "ro,subvolid=5", f"UUID={FSUUID}", "/mnt")))
    malformed_uuid = "-" * 36
    check("runtime rejects malformed dash-heavy UUID", not SystemRuntimeBackend._allowed(("mount", "-t", "btrfs", "-o", "ro,subvolid=5", f"UUID={malformed_uuid}", f"/run/maho-l3/{TX}")))
    check("runtime refuses subvolume deletion", not SystemRuntimeBackend._allowed(("btrfs", "subvolume", "delete", "/@")))

    print("ALL SYSTEM RESTORE RUNTIME CONTRACTS PASS")


if __name__ == "__main__":
    main()
