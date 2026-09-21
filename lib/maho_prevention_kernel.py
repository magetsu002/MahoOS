#!/usr/bin/env python3
"""Userspace projection for the pinned Maho BPF LSM maps."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import platform
import stat
import struct
import subprocess
from typing import Iterable

from guardian_admission import EffectKind
from maho_mutation_authority import MutationAuthority, process_identity
from maho_prevention_policy import MutationOperation
from maho_process_control import ProcessControlAuthority, signal_mask


EFFECT_BITS = {effect: 1 << index for index, effect in enumerate(EffectKind)}
OPERATION_BITS = {
    # Opening with O_TRUNC crosses inode_setattr before file_open.  WRITE
    # therefore projects to both kernel hooks, while standalone SETATTR remains
    # independently authorizable.
    MutationOperation.WRITE: (1 << 0) | (1 << 6),
    MutationOperation.CREATE: 1 << 1,
    MutationOperation.UNLINK: 1 << 2,
    MutationOperation.RENAME: 1 << 3,
    MutationOperation.LINK: 1 << 4,
    MutationOperation.SYMLINK: 1 << 5,
    MutationOperation.SETATTR: 1 << 6,
    MutationOperation.MOUNT: 1 << 7,
    MutationOperation.REMOUNT: 1 << 7,
    MutationOperation.DEVICE_WRITE: 1 << 8,
    MutationOperation.SIGNAL: 1 << 9,
}


@dataclass(frozen=True)
class EnforcementRoot:
    path: str
    effect: EffectKind
    recursive: bool = True
    required: bool = False


def enforcement_roots(*, owner_home: str | None = None) -> tuple[EnforcementRoot, ...]:
    """Single projection of the canonical protected domains into inode roots."""
    roots = [
        EnforcementRoot("/", EffectKind.FILE, recursive=False, required=True),
        EnforcementRoot("/boot", EffectKind.BOOT_STATE, required=True),
        EnforcementRoot("/efi", EffectKind.BOOT_STATE),
        EnforcementRoot("/var/lib/pacman", EffectKind.PACKAGE_FILE_OVERRIDE, required=True),
        EnforcementRoot("/var/lib/maho/guardian", EffectKind.PRIVILEGE_AUTHORITY),
        EnforcementRoot("/var/lib/maho/recovery", EffectKind.BOOT_STATE),
        EnforcementRoot("/var/lib/maho/guardian-recovery-r3", EffectKind.BOOT_STATE),
        EnforcementRoot("/var/lib/maho/generations", EffectKind.BOOT_STATE),
        EnforcementRoot("/var/lib/maho/boot-authority", EffectKind.BOOT_STATE),
        EnforcementRoot("/usr/lib/maho", EffectKind.PRIVILEGE_AUTHORITY),
        EnforcementRoot("/usr/bin", EffectKind.PACKAGE_FILE_OVERRIDE),
        EnforcementRoot("/usr/sbin", EffectKind.PACKAGE_FILE_OVERRIDE),
        EnforcementRoot("/usr/lib", EffectKind.PACKAGE_FILE_OVERRIDE),
        EnforcementRoot("/etc/systemd/system", EffectKind.SYSTEM_SERVICE),
        EnforcementRoot("/etc/sudoers", EffectKind.PRIVILEGE_AUTHORITY, recursive=False),
        EnforcementRoot("/etc/sudoers.d", EffectKind.PRIVILEGE_AUTHORITY),
        EnforcementRoot("/etc/polkit-1", EffectKind.PRIVILEGE_AUTHORITY),
        EnforcementRoot("/etc/pam.d", EffectKind.PRIVILEGE_AUTHORITY),
        EnforcementRoot("/etc/ld.so.preload", EffectKind.LOADER_POLICY, recursive=False),
        EnforcementRoot("/etc/ld.so.conf.d", EffectKind.LOADER_POLICY),
        EnforcementRoot("/etc/modules-load.d", EffectKind.KERNEL_MODULE),
        EnforcementRoot("/etc/modprobe.d", EffectKind.KERNEL_MODULE),
    ]
    if owner_home:
        roots.append(EnforcementRoot(str(Path(owner_home) / ".local/share/maho/runtime"), EffectKind.FILE))
    return tuple(roots)


def host_device_roots() -> tuple[EnforcementRoot, ...]:
    """Resolve live mount devices without trusting a command or path spelling."""
    roots: list[EnforcementRoot] = []
    for mount, effect in (("/", EffectKind.FILE), ("/boot", EffectKind.BOOT_STATE)):
        try:
            info = os.stat(mount)
        except OSError:
            continue
        device = Path(f"/dev/block/{os.major(info.st_dev)}:{os.minor(info.st_dev)}")
        if device.exists():
            roots.append(EnforcementRoot(str(device.resolve()), effect, recursive=False, required=True))
    return tuple(roots)


def activation_scope_specs(roots: Iterable[EnforcementRoot]) -> tuple[str, ...]:
    specs: list[str] = []
    for root in roots:
        if not os.path.exists(root.path):
            if root.required:
                raise FileNotFoundError(root.path)
            continue
        specs.append(f"{EFFECT_BITS[root.effect]}:{1 if root.recursive else 0}:{root.path}")
    return tuple(specs)


def activate(loader: Path, object_path: Path, pin_root: Path, roots: Iterable[EnforcementRoot]) -> None:
    if os.geteuid() != 0:
        raise PermissionError("prevention activation requires authenticated administration")
    command = [str(loader), "load", str(object_path), str(pin_root), *activation_scope_specs(roots)]
    subprocess.run(command, check=True)


_SYS_BPF = 321 if platform.machine() == "x86_64" else 280 if platform.machine() == "aarch64" else None
_BPF_MAP_UPDATE_ELEM = 2
_BPF_OBJ_GET = 7
_BPF_ANY = 0
_LIBC = ctypes.CDLL(None, use_errno=True)


def _bpf(command: int, attribute: ctypes.Structure) -> int:
    if _SYS_BPF is None:
        raise OSError("unsupported architecture for BPF syscall projection")
    result = _LIBC.syscall(_SYS_BPF, command, ctypes.byref(attribute), ctypes.sizeof(attribute))
    if result < 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))
    return int(result)


class _ObjGet(ctypes.Structure):
    _fields_ = [("pathname", ctypes.c_uint64), ("bpf_fd", ctypes.c_uint32),
                ("file_flags", ctypes.c_uint32), ("path_fd", ctypes.c_int32)]


class _MapElem(ctypes.Structure):
    _fields_ = [("map_fd", ctypes.c_uint32), ("pad", ctypes.c_uint32),
                ("key", ctypes.c_uint64), ("value", ctypes.c_uint64),
                ("flags", ctypes.c_uint64)]


def _object_get(path: Path) -> int:
    encoded = ctypes.create_string_buffer(os.fsencode(path) + b"\0")
    return _bpf(_BPF_OBJ_GET, _ObjGet(ctypes.addressof(encoded), 0, 0, 0))


def _map_update(fd: int, key: bytes, value: bytes) -> None:
    key_buffer = ctypes.create_string_buffer(key)
    value_buffer = ctypes.create_string_buffer(value)
    _bpf(_BPF_MAP_UPDATE_ELEM, _MapElem(
        fd, 0, ctypes.addressof(key_buffer), ctypes.addressof(value_buffer), _BPF_ANY,
    ))


def project_authority(authority: MutationAuthority, map_path: Path) -> int:
    """Project an already authenticated envelope into exact inode authorities."""
    if process_identity(authority.subject.pid) != authority.subject:
        raise PermissionError("authority subject identity is no longer current")
    effect_mask = sum(EFFECT_BITS[item] for item in authority.effects)
    operation_mask = sum(OPERATION_BITS[item] for item in authority.operations)
    transaction_tag = int.from_bytes(hashlib.sha256(authority.transaction_id.encode()).digest()[:8], "little")
    fd = _object_get(map_path)
    device_fd: int | None = None
    projected = 0
    try:
        for target in authority.target_prefixes:
            info = os.stat(target, follow_symlinks=False)
            key = struct.pack(
                "=IIQQQQQ", authority.subject.pid, 0,
                authority.subject.start_time_ticks, authority.subject.executable_device,
                authority.subject.executable_inode, info.st_dev, info.st_ino,
            )
            value = struct.pack("=QQQQ", authority.expires_at_ns, effect_mask, operation_mask, transaction_tag)
            _map_update(fd, key, value)
            projected += 1
            if stat.S_ISBLK(info.st_mode):
                if device_fd is None:
                    device_fd = _object_get(map_path.with_name("device_authorities"))
                device_key = struct.pack(
                    "=IIQQQQ", authority.subject.pid, 0,
                    authority.subject.start_time_ticks, authority.subject.executable_device,
                    authority.subject.executable_inode,
                    (os.major(info.st_rdev) << 20) | os.minor(info.st_rdev),
                )
                _map_update(device_fd, device_key, value)
                projected += 1
    finally:
        os.close(fd)
        if device_fd is not None:
            os.close(device_fd)
    return projected


def _process_key(identity) -> bytes:
    return struct.pack(
        "=IIQQQ", identity.pid, 0, identity.start_time_ticks,
        identity.executable_device, identity.executable_inode,
    )


def register_protected_process(pid: int, map_path: Path, effect: EffectKind) -> object:
    """Register one live process identity; PID reuse cannot inherit protection."""
    identity = process_identity(pid)
    fd = _object_get(map_path)
    try:
        _map_update(fd, _process_key(identity), struct.pack("=QII", EFFECT_BITS[effect], 0, 0))
    finally:
        os.close(fd)
    return identity


def project_process_authority(authority: ProcessControlAuthority, map_path: Path) -> int:
    """Project exact caller→target signal authority after both identities revalidate."""
    if process_identity(authority.subject.pid) != authority.subject:
        raise PermissionError("process authority subject identity is no longer current")
    if process_identity(authority.target.pid) != authority.target:
        raise PermissionError("process authority target identity is no longer current")
    key = _process_key(authority.subject) + _process_key(authority.target)
    transaction_tag = int.from_bytes(
        hashlib.sha256(authority.transaction_id.encode()).digest()[:8], "little",
    )
    value = struct.pack(
        "=QQQQ", authority.expires_at_ns, EFFECT_BITS[authority.effect],
        signal_mask(authority.signals), transaction_tag,
    )
    fd = _object_get(map_path)
    try:
        _map_update(fd, key, value)
    finally:
        os.close(fd)
    return 1


def kernel_capabilities() -> dict[str, object]:
    lsm = Path("/sys/kernel/security/lsm").read_text().strip().split(",") if Path("/sys/kernel/security/lsm").is_file() else []
    return {
        "bpf_lsm_active": "bpf" in lsm,
        "kernel_btf": Path("/sys/kernel/btf/vmlinux").is_file(),
        "bpffs": Path("/sys/fs/bpf").is_mount(),
        "pin_root_active": Path("/sys/fs/bpf/maho-prevention/maps/enforcement_state").exists(),
    }
