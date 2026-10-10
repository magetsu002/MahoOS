#!/usr/bin/env python3
"""Fresh read-only attribution, scoped to the observer's live host mount view.

The accepted publication is owner evidence, not a measurement. Kernel ioctls on
an opened root and independent package/boot observations must agree with it.
No observation is cached, persisted, or consumed as mutation authority.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import time
from typing import Iterator, Mapping
from uuid import UUID

from maho_live_generation import read_live_publication
from maho_trust_identity import canonical_bytes
from maho_update_receipts import build_receipt
from maho_update_state import validate_transaction


class ObservationUnavailable(ValueError):
    pass


def _identity(st: os.stat_result) -> tuple[int, ...]:
    return (st.st_dev, st.st_ino, st.st_mode, st.st_uid, st.st_gid,
            st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class ProtectedInputs:
    """Open each ancestor without symlink traversal and retain read identities."""
    def __init__(self) -> None:
        self.identities: dict[Path, tuple[int, ...]] = {}

    @contextmanager
    def opened(self, path: Path) -> Iterator[int]:
        if not path.is_absolute() or '..' in path.parts:
            raise ObservationUnavailable('invalid protected path')
        descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for index, part in enumerate(path.parts):
                if index:
                    child = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                    dir_fd=descriptor)
                    os.close(descriptor)
                    descriptor = child
                st = os.fstat(descriptor)
                if st.st_uid != 0 or st.st_mode & 0o022:
                    raise ObservationUnavailable('untrusted input owner or permissions')
                current = Path(*path.parts[:index+1])
                identity = _identity(st)
                # Directory size/mtime can change for unrelated owner writes.
                if stat.S_ISDIR(st.st_mode):
                    identity = identity[:5]
                if current in self.identities and self.identities[current] != identity:
                    raise ObservationUnavailable('protected input changed')
                self.identities[current] = identity
            if not stat.S_ISREG(st.st_mode):
                raise ObservationUnavailable('protected input is not regular')
            yield descriptor
            if _identity(os.fstat(descriptor)) != identity:
                raise ObservationUnavailable('input changed during read')
        finally:
            os.close(descriptor)

    def read(self, path: Path) -> bytes:
        with self.opened(path) as descriptor:
            data = os.read(descriptor, 4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ObservationUnavailable('oversized generation input')
            return data

    def digest(self, path: Path) -> str:
        with self.opened(path) as descriptor:
            if os.fstat(descriptor).st_size > 1024 * 1024 * 1024:
                raise ObservationUnavailable('oversized boot artifact')
            digest = hashlib.sha256()
            while data := os.read(descriptor, 1024 * 1024):
                digest.update(data)
            return digest.hexdigest()

    def verify_unchanged(self) -> None:
        for path in tuple(self.identities):
            # Opening each file rechecks every ancestor and the original inode,
            # timestamps and mode, including publication replacement/ABA edits.
            if len(self.identities[path]) > 5:
                with self.opened(path):
                    pass


def root_identity(descriptor: int) -> dict[str, str]:
    # Linux x86_64/aarch64 UAPI _IOR layouts (btrfs.h); zero reserved fields.
    # These two read-only ioctls require no CAP_SYS_ADMIN, unlike TREE_SEARCH.
    if struct.calcsize('P') != 8:
        raise ObservationUnavailable('unsupported Btrfs ioctl ABI')
    fs, sub = bytearray(1024), bytearray(504)
    fcntl.ioctl(descriptor, 0x8400941f, fs, True)  # BTRFS_IOC_FS_INFO
    fcntl.ioctl(descriptor, 0x81f8943c, sub, True)  # GET_SUBVOL_INFO
    filesystem, subvolume = UUID(bytes=bytes(fs[16:32])), UUID(bytes=bytes(sub[296:312]))
    if not filesystem.int or not subvolume.int or os.fstat(descriptor).st_ino != 256:
        raise ObservationUnavailable('running root identity missing')
    return {'filesystem_uuid': str(filesystem), 'root_subvolume_uuid': str(subvolume)}


def _boot_context(proc: Path, descriptor: int) -> tuple[str, str, str, str]:
    # PID 1's namespace symlink is ptrace-restricted on some hosts. Kernel
    # mountinfo is readable and supplies mount IDs plus the entire mount view.
    if proc != Path('/proc') or proc.is_symlink():
        raise ObservationUnavailable('non-kernel proc source')
    if (proc / 'self/uid_map').read_text().split() != ['0', '0', '4294967295']:
        raise ObservationUnavailable('observer is in a user namespace')
    pids = [line.split()[1:] for line in (proc / 'self/status').read_text().splitlines()
            if line.startswith('NSpid:')]
    if len(pids) != 1 or len(pids[0]) != 1:
        raise ObservationUnavailable('observer is in a PID namespace')
    view = (proc / 'self/mountinfo').read_text()
    if view != (proc / '1/mountinfo').read_text():
        raise ObservationUnavailable('observer is outside host mount view')
    roots = [line.split() for line in view.splitlines() if line.split()[4] == '/']
    # Btrfs st_dev is per-subvolume and differs from mountinfo's superblock
    # device; fdinfo binds the open root to its actual kernel mount ID.
    mount_id = next(line.split(':', 1)[1].strip() for line in
                    (proc / f'self/fdinfo/{descriptor}').read_text().splitlines()
                    if line.startswith('mnt_id:'))
    if len(roots) != 1 or roots[0][0] != mount_id or roots[0][3:5] != ['/@', '/']:
        raise ObservationUnavailable('running root mount mismatch')
    if roots[0][roots[0].index('-')+1] != 'btrfs':
        raise ObservationUnavailable('running root is not Btrfs')
    boot_id = str(UUID((proc / 'sys/kernel/random/boot_id').read_text().strip()))
    return boot_id, os.uname().release, (proc / 'cmdline').read_text().strip(), view


def _packages(expected: Mapping[str, str]) -> dict[str, str]:
    if not expected or any(not re.fullmatch(r'[a-zA-Z0-9@._+:-]+', name)
                           or name.startswith('-') or not isinstance(version, str)
                           for name, version in expected.items()):
        raise ObservationUnavailable('accepted package inventory invalid')
    if Path('/var/lib/pacman/db.lck').exists():
        raise ObservationUnavailable('package mutation is in progress')
    result = subprocess.run(('/usr/bin/pacman', '-Q', '--', *sorted(expected)),
                            text=True, capture_output=True, check=True, timeout=5,
                            env={'PATH': '/usr/bin', 'LC_ALL': 'C'})
    rows = [line.split(' ', 1) for line in result.stdout.splitlines()]
    if any(len(row) != 2 for row in rows) or len(rows) != len(expected):
        raise ObservationUnavailable('incomplete installed package observation')
    return dict(rows)


def attribute_running_generation(
    generation_root: Path, update_root: Path, *, proc: Path = Path('/proc'),
) -> dict | None:
    """Return a freshly matched accepted publication, never the active candidate.

    This establishes root UUID/package-version/boot-content attribution under
    the current kernel. It grants neither recovery eligibility nor Signed Boot,
    package-file integrity, running-process identity or mutation authority.
    """
    started = time.monotonic()
    inputs = ProtectedInputs()
    try:
        publication = read_live_publication(generation_root, read_bytes=inputs.read)
        if publication is None:
            return None
        digest = publication['root_manifest_artifact_id'][4:]
        proof = json.loads(inputs.read(generation_root / 'artifacts/sha256' / digest[:2] / digest[2:]))
        if proof['kind'] == 'maho-initial-root-manifest':
            expected = publication['package_versions']
        else:
            txid = publication['transaction_id']
            if not re.fullmatch(r'upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}', txid):
                return None
            tx = validate_transaction(json.loads(inputs.read(update_root / 'transactions' / f'{txid}.json')))
            if (tx['state'] != 'HEALTHY' or tx['blockers'] or tx['transaction_id'] != txid
                or tx['source_revision'] != publication['source_revision']
                or tx['package_generation']['id'] != publication['package_generation_id']):
                return None
            if proof['kind'] == 'maho-live-root-proof' and hashlib.sha256(
                    canonical_bytes(build_receipt(tx))).hexdigest() != proof.get('receipt_sha256'):
                return None
            expected = {p['name']: p['candidate_version'] for p in tx['package_generation']['packages']}
        # Validate the executable through the same protected-path boundary.
        with inputs.opened(Path('/usr/bin/pacman')):
            pass
        root = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            observed = root_identity(root)
            context = _boot_context(proc, root)
            if any(observed[key] != publication[key] for key in observed):
                return None
            if context[1] != publication['running_kernel'] or hashlib.sha256(
                    context[2].encode()).hexdigest() != publication['cmdline_sha256']:
                return None
            tokens = context[2].split()
            if f"root=UUID={observed['filesystem_uuid']}" not in tokens or 'rootflags=subvol=@' not in tokens:
                return None
            if _packages(expected) != expected:
                return None
            boot = publication['boot_sha256']
            if not isinstance(boot, Mapping) or not boot:
                return None
            for path, expected_hash in boot.items():
                if not path.startswith('/boot/') or inputs.digest(Path(path)) != expected_hash:
                    return None
            if _packages(expected) != expected or Path('/var/lib/pacman/db.lck').exists():
                return None
            # Reopen / as well: a retained descriptor alone would overlook a
            # concurrently replaced mount. Compare both to the accepted UUIDs.
            current = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                if root_identity(root) != observed or root_identity(current) != observed:
                    return None
            finally:
                os.close(current)
            if _boot_context(proc, root) != context:
                return None
            inputs.verify_unchanged()
            if time.monotonic() - started > 15:
                return None
            return publication
        finally:
            os.close(root)
    except (OSError, ValueError, KeyError, TypeError, IndexError, StopIteration, subprocess.SubprocessError):
        return None
