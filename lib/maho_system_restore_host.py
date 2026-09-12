#!/usr/bin/env python3
"""Narrow root-host adapter for MahoOS L3 preparation evidence and backup creation."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Protocol, Sequence

_SNAPSHOT_PATH = re.compile(r"/\.snapshots/([1-9][0-9]*)/snapshot")
_TXID = re.compile(r"l3-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
_HASH_NAME = re.compile(r"^[A-Za-z0-9._+-]+_sha256_([0-9a-f]{64})$")
_REQUIRED_KERNELS = {
    "vmlinuz-linux-cachyos": "linux-cachyos",
    "vmlinuz-linux-cachyos-lts": "linux-cachyos-lts",
}


@dataclass(frozen=True)
class HostCommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


class HostBackend(Protocol):
    def run(self, argv: Sequence[str]) -> HostCommandResult: ...
    def read_text(self, path: str) -> str | None: ...
    def read_bytes(self, path: str) -> bytes | None: ...
    def exists(self, path: str) -> bool: ...
    def euid(self) -> int: ...


class SystemHostBackend:
    """Execute only exact command shapes needed by the L3 preparation host."""

    @staticmethod
    def _allowed(args: tuple[str, ...]) -> bool:
        if args[:4] == ("snapper", "-c", "root", "create"):
            if len(args) != 10 or args[4:7] != ("--read-only", "--print-number", "--description") or args[8] != "--userdata":
                return False
            descriptions = {
                "Maho L3 emergency backup ": "important=yes,maho.restore_backup=yes,maho.transaction={txid}",
                "Maho L3 native target ": "important=yes,maho.known_good=yes,maho.l3_target=yes,maho.transaction={txid}",
            }
            for prefix, userdata_template in descriptions.items():
                if not args[7].startswith(prefix):
                    continue
                txid = args[7][len(prefix):]
                if not _TXID.fullmatch(txid):
                    return False
                expected_userdata = userdata_template.format(txid=txid)
                return args[9] == expected_userdata
            return False
        if len(args) == 6 and args[:3] == ("findmnt", "--json", "--target"):
            return args[3] == "/home" and args[4:] == ("--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID")
        if len(args) == 4 and args[:3] == ("btrfs", "subvolume", "show"):
            return args[3] == "/home" or bool(_SNAPSHOT_PATH.fullmatch(args[3]))
        if len(args) == 6 and args[:4] == ("btrfs", "property", "get", "-ts"):
            return bool(_SNAPSHOT_PATH.fullmatch(args[4])) and args[5] == "ro"
        return False

    def run(self, argv: Sequence[str]) -> HostCommandResult:
        args = tuple(str(item) for item in argv)
        if not self._allowed(args):
            raise RuntimeError(f"L3 host refused command shape: {args!r}")
        proc = subprocess.run(args, text=True, capture_output=True, check=False, timeout=15)
        return HostCommandResult(proc.returncode, proc.stdout, proc.stderr)

    def read_text(self, path: str) -> str | None:
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    def read_bytes(self, path: str) -> bytes | None:
        try:
            return Path(path).read_bytes()
        except OSError:
            return None

    def exists(self, path: str) -> bool:
        return Path(path).exists()

    def euid(self) -> int:
        return os.geteuid()


def _subvolume_field(text: str, field: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(field)}:\s*(\S+)\s*$", text)
    if not match or match.group(1) in {"-", "none", "None"}:
        return None
    return match.group(1)

def _snapshot_id(row: object) -> int | None:
    if not isinstance(row, dict):
        return None
    value = row.get("snapperID")
    if isinstance(value, dict):
        value = value.get("snapshotID")
    return value if isinstance(value, int) and value > 0 else None


def _kernel_package(entry: object) -> tuple[str | None, str | None]:
    if not isinstance(entry, dict):
        return None, None
    images = entry.get("imageDetails")
    if not isinstance(images, list):
        return None, None
    for image in images:
        if not isinstance(image, dict) or image.get("limineKey") != "KERNEL_PATH":
            continue
        name = image.get("fileName")
        if isinstance(name, str) and name in _REQUIRED_KERNELS:
            return _REQUIRED_KERNELS[name], name
    return None, None


def _artifact_verified(
    image: object,
    *,
    history_root: Path,
    backend: HostBackend,
) -> bool:
    if not isinstance(image, dict):
        return False
    name = image.get("fileHashName")
    if not isinstance(name, str):
        return False
    match = _HASH_NAME.fullmatch(name)
    if not match:
        return False
    data = backend.read_bytes(str(history_root / name))
    return data is not None and hashlib.sha256(data).hexdigest() == match.group(1)

def _kernel_entry_verified(
    entry: object,
    *,
    snapshot_id: int,
    history_root: Path,
    backend: HostBackend,
) -> tuple[str | None, bool, bool]:
    package, kernel_name = _kernel_package(entry)
    if package is None or kernel_name is None or not isinstance(entry, dict):
        return None, False, False
    images = entry.get("imageDetails")
    if not isinstance(images, list) or not images:
        return package, False, False
    expected_initramfs = "initramfs-linux-cachyos-lts.img" if package.endswith("-lts") else "initramfs-linux-cachyos.img"
    filenames = {str(item.get("fileName")) for item in images if isinstance(item, dict)}
    required_images = {kernel_name, expected_initramfs}
    files_verified = required_images.issubset(filenames) and all(
        _artifact_verified(item, history_root=history_root, backend=backend)
        for item in images
    )
    rows = entry.get("cmdlineDetails")
    expected_root = f"rootflags=subvol=/@snapshots/{snapshot_id}/snapshot"
    flagged = False
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = row.get("snapshotCmdline")
            if isinstance(value, str):
                tokens = set(value.split())
                if expected_root in tokens and "maho.recovery_snapshot=1" in tokens:
                    flagged = True
                    break
    return package, files_verified, flagged

def _manifest_backup_evidence(
    manifest_text: str | None,
    *,
    snapshot_id: int,
    boot_root: Path,
    machine_id: str,
    backend: HostBackend,
) -> dict[str, object]:
    result: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "boot_state_coherent": False,
        "files_verified": False,
        "recovery_overlay_flagged": False,
        "kernel_packages": [],
    }
    if not manifest_text:
        return result
    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError:
        return result
    rows = manifest.get("snapshotEntries") if isinstance(manifest, dict) else None
    if not isinstance(rows, list):
        return result
    row = next((item for item in rows if _snapshot_id(item) == snapshot_id), None)
    if not isinstance(row, dict):
        return result
    kernels = row.get("kernelEntries")
    if not isinstance(kernels, list):
        return result

    history_root = boot_root / machine_id / "limine_history"
    packages: set[str] = set()
    all_files = True
    all_flagged = True
    for entry in kernels:
        package, files_ok, flagged = _kernel_entry_verified(
            entry, snapshot_id=snapshot_id, history_root=history_root, backend=backend
        )
        if package is None:
            continue
        packages.add(package)
        all_files = all_files and files_ok
        all_flagged = all_flagged and flagged
    required = {"linux-cachyos", "linux-cachyos-lts"}
    complete = required.issubset(packages)
    result["kernel_packages"] = sorted(packages)
    result["files_verified"] = bool(complete and all_files)
    result["recovery_overlay_flagged"] = bool(complete and all_flagged)
    result["boot_state_coherent"] = bool(
        complete and all_files and all_flagged
    )
    return result


class SystemPreparationOps:
    def __init__(
        self,
        *,
        machine_id: str,
        boot_root: str | Path = "/boot",
        backend: HostBackend | None = None,
        timeout_seconds: float = 60.0,
        poll_seconds: float = 1.0,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
            raise ValueError("invalid machine id")
        self.machine_id = machine_id
        self.boot_root = Path(boot_root)
        self.backend = backend or SystemHostBackend()
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    @property
    def manifest_path(self) -> Path:
        return self.boot_root / self.machine_id / "limine_history" / "snapshots.json"

    def create_known_good_target(self, transaction_id: str) -> int:
        if self.backend.euid() != 0:
            raise PermissionError("L3 target snapshot creation requires root")
        if not _TXID.fullmatch(transaction_id):
            raise ValueError("invalid L3 transaction id")
        description = f"Maho L3 native target {transaction_id}"
        userdata = (
            "important=yes,maho.known_good=yes,maho.l3_target=yes,"
            f"maho.transaction={transaction_id}"
        )
        result = self.backend.run((
            "snapper", "-c", "root", "create",
            "--read-only", "--print-number",
            "--description", description,
            "--userdata", userdata,
        ))
        value = result.stdout.strip()
        if result.returncode != 0 or not re.fullmatch(r"[1-9][0-9]*", value):
            raise RuntimeError("Snapper did not create one bounded L3 target snapshot")
        return int(value)

    def create_emergency_snapshot(self, transaction_id: str) -> int:
        if self.backend.euid() != 0:
            raise PermissionError("L3 emergency snapshot creation requires root")
        if not _TXID.fullmatch(transaction_id):
            raise ValueError("invalid L3 transaction id")
        description = f"Maho L3 emergency backup {transaction_id}"
        userdata = (
            "important=yes,maho.restore_backup=yes,"
            f"maho.transaction={transaction_id}"
        )
        result = self.backend.run((
            "snapper", "-c", "root", "create",
            "--read-only", "--print-number",
            "--description", description,
            "--userdata", userdata,
        ))
        value = result.stdout.strip()
        if result.returncode != 0 or not re.fullmatch(r"[1-9][0-9]*", value):
            raise RuntimeError("Snapper did not create one bounded emergency snapshot")
        return int(value)

    def snapshot_uuid(self, snapshot_id: int) -> str:
        path = f"/.snapshots/{snapshot_id}/snapshot"
        result = self.backend.run(("btrfs", "subvolume", "show", path))
        value = _subvolume_field(result.stdout, "UUID") if result.returncode == 0 else None
        if value is None:
            raise RuntimeError(f"cannot verify snapshot {snapshot_id} UUID")
        return value

    def home_identity(self) -> dict[str, str]:
        mount = self.backend.run((
            "findmnt", "--json", "--target", "/home",
            "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID",
        ))
        if mount.returncode != 0:
            raise RuntimeError("cannot inspect /home mount identity")
        try:
            data = json.loads(mount.stdout)
            filesystems = data.get("filesystems") if isinstance(data, dict) else None
            row = filesystems[0] if isinstance(filesystems, list) and len(filesystems) == 1 else None
        except (json.JSONDecodeError, IndexError):
            row = None
        if not isinstance(row, dict):
            raise RuntimeError("invalid /home mount evidence")
        if row.get("fstype") != "btrfs" or row.get("fsroot") != "/@home":
            raise RuntimeError("/home is not the expected separate Btrfs subvolume")
        fs_uuid = row.get("uuid")
        if not isinstance(fs_uuid, str) or not fs_uuid:
            raise RuntimeError("/home filesystem UUID is unavailable")
        shown = self.backend.run(("btrfs", "subvolume", "show", "/home"))
        subvol_uuid = _subvolume_field(shown.stdout, "UUID") if shown.returncode == 0 else None
        if subvol_uuid is None:
            raise RuntimeError("/home subvolume UUID is unavailable")
        return {"filesystem_uuid": fs_uuid, "fsroot": "/@home", "subvolume_uuid": subvol_uuid}

    def _backup_evidence_once(self, snapshot_id: int) -> dict[str, object]:
        path = f"/.snapshots/{snapshot_id}/snapshot"
        evidence = _manifest_backup_evidence(
            self.backend.read_text(str(self.manifest_path)),
            snapshot_id=snapshot_id,
            boot_root=self.boot_root,
            machine_id=self.machine_id,
            backend=self.backend,
        )
        evidence["exists"] = self.backend.exists(path)
        evidence["snapshot_uuid"] = ""
        evidence["read_only"] = False
        if evidence["exists"]:
            shown = self.backend.run(("btrfs", "subvolume", "show", path))
            if shown.returncode == 0:
                evidence["snapshot_uuid"] = _subvolume_field(shown.stdout, "UUID") or ""
            prop = self.backend.run(("btrfs", "property", "get", "-ts", path, "ro"))
            evidence["read_only"] = prop.returncode == 0 and prop.stdout.strip() == "ro=true"
        return evidence

    def wait_for_backup(self, snapshot_id: int) -> dict[str, object]:
        if self.backend.euid() != 0:
            raise PermissionError("L3 emergency backup verification requires root")
        if not isinstance(snapshot_id, int) or snapshot_id <= 0:
            raise ValueError("invalid emergency snapshot id")
        deadline = time.monotonic() + self.timeout_seconds
        last: dict[str, object] = {"snapshot_id": snapshot_id}
        while True:
            last = self._backup_evidence_once(snapshot_id)
            ready = (
                bool(last.get("snapshot_uuid"))
                and last.get("exists") is True
                and last.get("read_only") is True
                and last.get("boot_state_coherent") is True
                and last.get("files_verified") is True
                and last.get("recovery_overlay_flagged") is True
            )
            if ready or time.monotonic() >= deadline:
                return last
            time.sleep(self.poll_seconds)
