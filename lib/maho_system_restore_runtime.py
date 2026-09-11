#!/usr/bin/env python3
"""Privileged structural evidence collectors for bounded MahoOS L3 restore."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Mapping, Protocol, Sequence

from maho_system_restore_host import SystemPreparationOps
from maho_system_restore_transaction import PostBootEvidence, StructuralEvidence

_UUID = re.compile(r"[0-9a-fA-F-]{36}")
_TXID = re.compile(r"l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
_KERNEL_VERSION = re.compile(r"[A-Za-z0-9._+-]+")
_FINDMNT_OUTPUT = "TARGET,SOURCE,FSTYPE,FSROOT,UUID"
_BOOT_PATHS = {
    "linux-cachyos": ("/boot/vmlinuz-linux-cachyos", "/boot/initramfs-linux-cachyos.img"),
    "linux-cachyos-lts": ("/boot/vmlinuz-linux-cachyos-lts", "/boot/initramfs-linux-cachyos-lts.img"),
}


class RuntimeCommandResult:
    def __init__(self, returncode: int, stdout: str, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RuntimeBackend(Protocol):
    def run(self, argv: Sequence[str]) -> RuntimeCommandResult: ...
    def read_text(self, path: str) -> str | None: ...
    def read_bytes(self, path: str) -> bytes | None: ...
    def mkdir(self, path: str) -> None: ...
    def rmdir(self, path: str) -> None: ...
    def euid(self) -> int: ...


def _mountpoint(txid: str) -> str:
    if not _TXID.fullmatch(txid):
        raise ValueError("invalid L3 transaction id")
    return f"/run/maho-l3/{txid}"


def _safe_uuid(value: str) -> bool:
    return bool(_UUID.fullmatch(value))


class SystemRuntimeBackend:
    @staticmethod
    def _allowed(args: tuple[str, ...]) -> bool:
        if len(args) == 6 and args[:3] == ("findmnt", "--json", "--target"):
            return args[3] in {"/", "/home"} and args[4:] == ("--output", _FINDMNT_OUTPUT)
        if args == ("uname", "-r"):
            return True
        if len(args) == 3 and args[:2] == ("pacman", "-Q"):
            return args[2] in _BOOT_PATHS
        if len(args) == 4 and args[:3] == ("btrfs", "subvolume", "show"):
            path = args[3]
            return path == "/" or path == "/home" or bool(re.fullmatch(r"/\.snapshots/[1-9][0-9]*/snapshot", path)) or bool(re.fullmatch(r"/run/maho-l3/l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}/@", path))
        if len(args) == 6 and args[:4] == ("btrfs", "property", "get", "-ts"):
            return bool(re.fullmatch(r"/\.snapshots/[1-9][0-9]*/snapshot", args[4])) and args[5] == "ro"
        if len(args) == 7 and args[:4] == ("mount", "-t", "btrfs", "-o"):
            return args[4] == "ro,subvolid=5" and args[5].startswith("UUID=") and _safe_uuid(args[5][5:]) and bool(re.fullmatch(r"/run/maho-l3/l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", args[6]))
        if len(args) == 2 and args[0] == "umount":
            return bool(re.fullmatch(r"/run/maho-l3/l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", args[1]))
        return False

    def run(self, argv: Sequence[str]) -> RuntimeCommandResult:
        args = tuple(str(x) for x in argv)
        if not self._allowed(args):
            raise RuntimeError(f"L3 runtime refused command shape: {args!r}")
        proc = subprocess.run(args, text=True, capture_output=True, check=False, timeout=20)
        return RuntimeCommandResult(proc.returncode, proc.stdout, proc.stderr)

    def read_text(self, path: str) -> str | None:
        allowed_module = re.fullmatch(r"/usr/lib/modules/[A-Za-z0-9._+-]+/pkgbase", path)
        if path == "/proc/cmdline" or allowed_module:
            try:
                return Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                return None
        raise RuntimeError(f"L3 runtime refused read path: {path!r}")

    def read_bytes(self, path: str) -> bytes | None:
        allowed_boot = path in {item for pair in _BOOT_PATHS.values() for item in pair}
        allowed_running = bool(re.fullmatch(r"/usr/lib/modules/[A-Za-z0-9._+-]+/vmlinuz", path))
        if not (allowed_boot or allowed_running):
            raise RuntimeError(f"L3 runtime refused binary read path: {path!r}")
        try:
            return Path(path).read_bytes()
        except OSError:
            return None

    def mkdir(self, path: str) -> None:
        if not re.fullmatch(r"/run/maho-l3/l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", path):
            raise RuntimeError("L3 runtime refused mount directory")
        Path(path).mkdir(parents=True, mode=0o700, exist_ok=False)

    def rmdir(self, path: str) -> None:
        if not re.fullmatch(r"/run/maho-l3/l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}", path):
            raise RuntimeError("L3 runtime refused mount directory cleanup")
        Path(path).rmdir()

    def euid(self) -> int:
        return os.geteuid()


def _findmnt(backend: RuntimeBackend, target: str) -> Mapping[str, object]:
    result = backend.run(("findmnt", "--json", "--target", target, "--output", _FINDMNT_OUTPUT))
    if result.returncode != 0:
        raise RuntimeError(f"cannot inspect {target} mount")
    try:
        payload = json.loads(result.stdout)
        rows = payload.get("filesystems") if isinstance(payload, dict) else None
        row = rows[0] if isinstance(rows, list) and len(rows) == 1 else None
    except (json.JSONDecodeError, IndexError):
        row = None
    if not isinstance(row, dict):
        raise RuntimeError(f"invalid {target} mount evidence")
    return row


def _field(text: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}:\s*(\S+)\s*$", text)
    if not match or match.group(1) in {"-", "none", "None"}:
        raise RuntimeError(f"missing Btrfs {name}")
    return match.group(1)


def _hash(backend: RuntimeBackend, path: str) -> str:
    data = backend.read_bytes(path)
    if data is None:
        raise RuntimeError(f"cannot read boot artifact {path}")
    return hashlib.sha256(data).hexdigest()


def _boot_hashes(backend: RuntimeBackend, package: str) -> tuple[str, str]:
    paths = _BOOT_PATHS.get(package)
    if paths is None:
        raise RuntimeError("uncertified kernel package")
    return _hash(backend, paths[0]), _hash(backend, paths[1])


class SystemRestoreRuntimeOps:
    def __init__(
        self,
        journal: Mapping[str, object],
        *,
        machine_id: str,
        transaction_id: str,
        backend: RuntimeBackend | None = None,
        preparation_ops: SystemPreparationOps | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
            raise ValueError("invalid machine id")
        if not _TXID.fullmatch(transaction_id):
            raise ValueError("invalid L3 transaction id")
        self.journal = journal
        self.machine_id = machine_id
        self.transaction_id = transaction_id
        self.backend = backend or SystemRuntimeBackend()
        self.preparation_ops = preparation_ops or SystemPreparationOps(machine_id=machine_id)

    def _require_root(self) -> None:
        if self.backend.euid() != 0:
            raise PermissionError("L3 structural verification requires root")

    def _target(self) -> Mapping[str, object]:
        target = self.journal.get("target")
        if not isinstance(target, Mapping):
            raise RuntimeError("journal target missing")
        return target

    def _backup(self) -> Mapping[str, object]:
        backup = self.journal.get("backup")
        if not isinstance(backup, Mapping):
            raise RuntimeError("journal backup missing")
        return backup

    def structural_evidence(self) -> StructuralEvidence:
        """Verify replacement /@ while still booted in the recovery OverlayFS."""
        self._require_root()
        target = self._target()
        backup = self._backup()
        root_uuid = str(target.get("root_filesystem_uuid") or "")
        package = str(target.get("expected_kernel_package") or "")
        if not _safe_uuid(root_uuid):
            raise RuntimeError("journal root filesystem UUID is invalid")
        mountpoint = _mountpoint(self.transaction_id)
        self.backend.mkdir(mountpoint)
        mounted = False
        try:
            result = self.backend.run((
                "mount", "-t", "btrfs", "-o", "ro,subvolid=5",
                f"UUID={root_uuid}", mountpoint,
            ))
            if result.returncode != 0:
                raise RuntimeError("cannot mount Btrfs top-level read-only")
            mounted = True
            shown = self.backend.run(("btrfs", "subvolume", "show", f"{mountpoint}/@"))
            if shown.returncode != 0:
                raise RuntimeError("cannot inspect replacement @ subvolume")
            parent_uuid = _field(shown.stdout, "Parent UUID")
            kernel_hash, initramfs_hash = _boot_hashes(self.backend, package)
            home = self.preparation_ops.home_identity()
            backup_ev = self.preparation_ops.wait_for_backup(int(backup.get("snapshot_id") or 0))
            return StructuralEvidence(
                root_filesystem_uuid=root_uuid,
                root_parent_uuid=parent_uuid,
                root_fsroot="/@",
                kernel_sha256=kernel_hash,
                initramfs_sha256=initramfs_hash,
                home_filesystem_uuid=home["filesystem_uuid"],
                home_fsroot=home["fsroot"],
                home_subvolume_uuid=home["subvolume_uuid"],
                backup_snapshot_uuid=str(backup_ev.get("snapshot_uuid") or ""),
                backup_read_only=backup_ev.get("read_only") is True,
            )
        finally:
            if mounted:
                unmount = self.backend.run(("umount", mountpoint))
                if unmount.returncode != 0:
                    raise RuntimeError("cannot unmount L3 verification mount")
            self.backend.rmdir(mountpoint)

    def postboot_evidence(self) -> PostBootEvidence:
        """Collect normal-root proof after reboot without mutating the system."""
        self._require_root()
        target = self._target()
        backup = self._backup()
        root = _findmnt(self.backend, "/")
        root_fstype = str(root.get("fstype") or "")
        root_fsroot = str(root.get("fsroot") or "")
        root_uuid = str(root.get("uuid") or "")
        shown = self.backend.run(("btrfs", "subvolume", "show", "/"))
        if shown.returncode != 0:
            raise RuntimeError("cannot inspect restored live root")
        parent_uuid = _field(shown.stdout, "Parent UUID")

        package = str(target.get("expected_kernel_package") or "")
        pkg = self.backend.run(("pacman", "-Q", package))
        fields = pkg.stdout.strip().split() if pkg.returncode == 0 else []
        package_version = fields[1] if len(fields) == 2 and fields[0] == package else ""
        running = self.backend.run(("uname", "-r"))
        running_version = running.stdout.strip() if running.returncode == 0 else ""
        if running_version and not _KERNEL_VERSION.fullmatch(running_version):
            running_version = ""
        pkgbase = self.backend.read_text(f"/usr/lib/modules/{running_version}/pkgbase") if running_version else None
        running_package = (pkgbase or "").strip()
        running_image = self.backend.read_bytes(f"/usr/lib/modules/{running_version}/vmlinuz") if running_version else None
        running_hash = hashlib.sha256(running_image).hexdigest() if running_image is not None else ""
        kernel_hash, initramfs_hash = _boot_hashes(self.backend, package)
        home = self.preparation_ops.home_identity()
        backup_ev = self.preparation_ops.wait_for_backup(int(backup.get("snapshot_id") or 0))
        cmdline = self.backend.read_text("/proc/cmdline") or ""
        return PostBootEvidence(
            root_filesystem_uuid=root_uuid,
            root_parent_uuid=parent_uuid,
            root_fstype=root_fstype,
            root_fsroot=root_fsroot,
            recovery_overlay_active=root_fstype == "overlay",
            recovery_flag_present="maho.recovery_snapshot=1" in set(cmdline.split()),
            kernel_package=running_package if package_version else "",
            kernel_version=package_version,
            running_kernel_version=running_version,
            running_kernel_sha256=running_hash,
            kernel_sha256=kernel_hash,
            initramfs_sha256=initramfs_hash,
            home_filesystem_uuid=home["filesystem_uuid"],
            home_fsroot=home["fsroot"],
            home_subvolume_uuid=home["subvolume_uuid"],
            backup_snapshot_uuid=str(backup_ev.get("snapshot_uuid") or ""),
            backup_read_only=backup_ev.get("read_only") is True,
        )
