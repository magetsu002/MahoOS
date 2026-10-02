#!/usr/bin/env python3
"""Native Btrfs candidate-root execution and activation primitives for M4B."""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Mapping, Sequence

from maho_runtime_release import verify_release
from maho_system_restore_host import SystemPreparationOps
from maho_system_restore_journal import read_journal
from maho_update_discovery import CommandResult
from maho_update_transaction import ExecutionPlan, OfflineRootUpdateOps

_TXID = re.compile(r"upd-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}")
_UUID = re.compile(r"[0-9a-fA-F-]{36}")
_PACKAGE = re.compile(r"[A-Za-z0-9@._+:-]+")
BOOT_ARTIFACTS = (
    "/boot/intel-ucode.img",
    "/boot/initramfs-linux-cachyos-lts.img",
    "/boot/initramfs-linux-cachyos.img",
    "/boot/vmlinuz-linux-cachyos",
    "/boot/vmlinuz-linux-cachyos-lts",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _subvolume_field(output: str, name: str) -> str | None:
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == name:
            value = value.strip()
            return value if value and value != "-" else None
    return None


def candidate_name(transaction_id: str) -> str:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return "@maho-update-candidate-" + transaction_id.rsplit("-", 1)[1]


def backup_name(transaction_id: str) -> str:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return "@maho-update-backup-" + transaction_id.rsplit("-", 1)[1]


def admission_base_name(transaction_id: str) -> str:
    if _TXID.fullmatch(transaction_id) is None:
        raise ValueError("invalid update transaction identity")
    return "@maho-update-admission-base-" + transaction_id.rsplit("-", 1)[1]


def update_confirmation(transaction_id: str, package_generation_id: str) -> str:
    if _TXID.fullmatch(transaction_id) is None or not package_generation_id.startswith("pkg-"):
        raise ValueError("invalid update confirmation identity")
    return f"UPDATE:{transaction_id}:{package_generation_id}"


def activation_confirmation(transaction_id: str, candidate_uuid: str) -> str:
    if _TXID.fullmatch(transaction_id) is None or _UUID.fullmatch(candidate_uuid) is None:
        raise ValueError("invalid activation confirmation identity")
    return f"ACTIVATE:{transaction_id}:{candidate_uuid}"


def candidate_boot_proven(cmdline: Sequence[str], mount: Mapping[str, Any], root_uuid: str | None, candidate_uuid: str) -> bool:
    return (
        "maho.recovery_snapshot=1" not in cmdline
        and mount.get("fstype") == "btrfs"
        and mount.get("fsroot") == "/@"
        and root_uuid == candidate_uuid
    )


@dataclass(frozen=True)
class RootIdentity:
    filesystem_uuid: str
    fsroot: str
    source: str
    device: str
    subvolume_uuid: str


class NativeBtrfsOps:
    """Strict native host operations for one candidate-root transaction."""

    UNMOUNT_ATTEMPTS = 5
    UNMOUNT_RETRY_DELAY_SECONDS = 0.2

    def __init__(
        self, transaction_id: str, *,
        run_root: str | os.PathLike[str] = "/run/maho-update-m4b",
        boot_root: str | os.PathLike[str] = "/boot",
    ) -> None:
        if _TXID.fullmatch(transaction_id) is None:
            raise ValueError("invalid update transaction identity")
        self.transaction_id = transaction_id
        self.run_root = Path(run_root) / transaction_id
        self.boot_root = Path(boot_root)
        if not self.boot_root.is_absolute():
            raise ValueError("boot root must be absolute")
        self.top = self.run_root / "top"
        self.offline_root = self.run_root / "root"
        self.candidate = candidate_name(transaction_id)
        self.backup = backup_name(transaction_id)
        self.admission_base = admission_base_name(transaction_id)

    @staticmethod
    def _run(command: Sequence[str], *, check: bool = False) -> CommandResult:
        completed = subprocess.run(
            list(command), check=False, text=True, capture_output=True,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if check and completed.returncode != 0:
            raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}: {completed.stderr.strip()}")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    @staticmethod
    def require_root() -> None:
        if os.geteuid() != 0:
            raise PermissionError("M4B native host operations require root")

    def root_identity(self) -> RootIdentity:
        self.require_root()
        result = self._run((
            "findmnt", "--json", "--target", "/",
            "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID",
        ), check=True)
        try:
            rows = json.loads(result.stdout).get("filesystems", [])
            row = rows[0] if len(rows) == 1 else None
        except (json.JSONDecodeError, AttributeError, IndexError):
            row = None
        if not isinstance(row, Mapping) or row.get("fstype") != "btrfs":
            raise RuntimeError("native update requires a Btrfs root")
        fsroot = row.get("fsroot")
        fs_uuid = row.get("uuid")
        source = row.get("source")
        if not all(isinstance(item, str) and item for item in (fsroot, fs_uuid, source)):
            raise RuntimeError("root mount identity is incomplete")
        if fsroot != "/@":
            raise RuntimeError("native update preparation requires the normal /@ root")
        if "maho.recovery_snapshot=1" in Path("/proc/cmdline").read_text(encoding="utf-8"):
            raise RuntimeError("native update cannot run from recovery boot")
        shown = self._run(("btrfs", "subvolume", "show", "/"), check=True)
        subvol_uuid = _subvolume_field(shown.stdout, "UUID")
        if not subvol_uuid:
            raise RuntimeError("live root subvolume UUID is unavailable")
        device = source.split("[", 1)[0]
        if not device.startswith("/dev/"):
            device = f"/dev/disk/by-uuid/{fs_uuid}"
        return RootIdentity(fs_uuid, fsroot, source, device, subvol_uuid)

    def _mount_top(self, identity: RootIdentity, *, read_only: bool = False) -> None:
        self.run_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.top.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self._run(("mountpoint", "-q", str(self.top))).returncode == 0:
            return
        options = "subvolid=5,ro" if read_only else "subvolid=5"
        self._run(("mount", "-t", "btrfs", "-o", options, identity.device, str(self.top)), check=True)

    def _unmount(self, path: Path) -> None:
        if self._run(("mountpoint", "-q", str(path))).returncode != 0:
            return
        command = ("umount", str(path))
        result = None
        for attempt in range(self.UNMOUNT_ATTEMPTS):
            result = self._run(command)
            if result.returncode == 0:
                return
            # Another teardown path may have completed the unmount after our
            # failed attempt. Treat an already-gone mount as success rather
            # than turning harmless convergence into a recovery failure.
            if self._run(("mountpoint", "-q", str(path))).returncode != 0:
                return
            if attempt + 1 < self.UNMOUNT_ATTEMPTS:
                time.sleep(self.UNMOUNT_RETRY_DELAY_SECONDS)
        assert result is not None
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(command)}: {result.stderr.strip()}"
        )

    def close(self) -> None:
        self.unmount_normal_candidate_runtime()
        self._unmount(self.offline_root)
        self._unmount(self.top)

    def mount_normal_candidate_runtime(self) -> dict[str, Any]:
        """Mount a minimal isolated runtime needed by Pacman inside a normal candidate."""
        self.require_root()
        root = self.offline_root
        if self._run(("mountpoint", "-q", str(root))).returncode != 0:
            raise RuntimeError("normal candidate root is not mounted")
        for name in ("dev", "proc", "sys", "run"):
            path = root / name
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError(f"normal candidate runtime path is unsafe:{name}")
            if self._run(("mountpoint", "-q", str(path))).returncode == 0:
                raise RuntimeError(f"normal candidate runtime path already mounted:{name}")
        dev = root / "dev"
        proc = root / "proc"
        sys = root / "sys"
        run = root / "run"
        mounted: list[Path] = []
        nodes: list[Path] = []
        try:
            self._run(("mount", "-t", "tmpfs", "-o", "mode=0755,nosuid", "tmpfs", str(dev)), check=True)
            mounted.append(dev)
            for name in ("null", "zero", "random", "urandom"):
                target = dev / name
                target.touch(mode=0o600, exist_ok=False)
                self._run(("mount", "--bind", f"/dev/{name}", str(target)), check=True)
                nodes.append(target)
            (dev / "shm").mkdir(mode=0o1777)
            # mkinitcpio requires the conventional descriptor links provided by
            # a normal devtmpfs mount. Keep /dev isolated while exposing only
            # the candidate process's own descriptors through its private procfs.
            descriptor_links = {
                "fd": "/proc/self/fd",
                "stdin": "/proc/self/fd/0",
                "stdout": "/proc/self/fd/1",
                "stderr": "/proc/self/fd/2",
            }
            for name, target in descriptor_links.items():
                (dev / name).symlink_to(target)
            self._run(("mount", "-t", "proc", "-o", "nosuid,nodev,noexec", "proc", str(proc)), check=True)
            mounted.append(proc)
            self._run(("mount", "-t", "sysfs", "-o", "ro,nosuid,nodev,noexec", "sysfs", str(sys)), check=True)
            mounted.append(sys)
            self._run(("mount", "-t", "tmpfs", "-o", "mode=0755,nosuid,nodev", "tmpfs", str(run)), check=True)
            mounted.append(run)
        except Exception:
            for target in reversed(nodes):
                try: self._unmount(target)
                except Exception: pass
            for path in reversed(mounted):
                try: self._unmount(path)
                except Exception: pass
            raise
        return {
            "ok": True,
            "runtime": ["dev-minimal", "proc", "sys-ro", "run-private"],
            "device_links": descriptor_links,
        }

    def unmount_normal_candidate_runtime(self) -> None:
        root = self.offline_root
        dev = root / "dev"
        for name in ("urandom", "random", "zero", "null"):
            try: self._unmount(dev / name)
            except Exception: pass
        for name in ("run", "sys", "proc", "dev"):
            try: self._unmount(root / name)
            except Exception: pass

    def _show_uuid(self, path: Path) -> str:
        result = self._run(("btrfs", "subvolume", "show", str(path)), check=True)
        value = _subvolume_field(result.stdout, "UUID")
        if not value or _UUID.fullmatch(value) is None:
            raise RuntimeError(f"subvolume UUID unavailable: {path}")
        return value

    def _read_only(self, path: Path) -> bool:
        result = self._run(("btrfs", "property", "get", "-ts", str(path), "ro"), check=True)
        return result.stdout.strip() == "ro=true"

    def _set_read_only(self, path: Path, value: bool) -> None:
        self._run(("btrfs", "property", "set", "-ts", str(path), "ro", "true" if value else "false"), check=True)

    def create_candidate(self) -> dict[str, Any]:
        identity = self.root_identity()
        self._mount_top(identity)
        destination = self.top / self.candidate
        admission_base = self.top / self.admission_base
        if destination.exists():
            raise RuntimeError("candidate subvolume already exists")
        if admission_base.exists():
            raise RuntimeError("admission base subvolume already exists")
        if (self.top / self.backup).exists():
            raise RuntimeError("previous-root backup name already exists")

        # Freeze the exact pre-mutation root first, then derive the candidate
        # from that immutable base. Admission can therefore compare the
        # candidate against precisely what it inherited, not a later live /.
        self._run(("btrfs", "subvolume", "snapshot", "/", str(admission_base)), check=True)
        base_uuid = self._show_uuid(admission_base)
        self._set_read_only(admission_base, True)
        if not self._read_only(admission_base):
            raise RuntimeError("admission base did not become read-only")
        try:
            self._run(("btrfs", "subvolume", "snapshot", str(admission_base), str(destination)), check=True)
            self._set_read_only(destination, False)
            uuid = self._show_uuid(destination)
            self.offline_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            self._run((
                "mount", "-t", "btrfs", "-o", f"subvol={self.candidate}",
                identity.device, str(self.offline_root),
            ), check=True)
            mounted = self._run(("findmnt", "-no", "FSROOT", str(self.offline_root)), check=True).stdout.strip()
            if mounted != f"/{self.candidate}":
                self.close()
                raise RuntimeError("candidate root mounted with unexpected Btrfs identity")
        except Exception:
            if destination.exists():
                self._set_read_only(destination, False)
                self._run(("btrfs", "subvolume", "delete", str(destination)))
            if admission_base.exists():
                self._set_read_only(admission_base, False)
                self._run(("btrfs", "subvolume", "delete", str(admission_base)))
            raise
        return {
            "name": self.candidate,
            "uuid": uuid,
            "parent_root_uuid": identity.subvolume_uuid,
            "filesystem_uuid": identity.filesystem_uuid,
            "offline_root": str(self.offline_root),
            "admission_base_name": self.admission_base,
            "admission_base_uuid": base_uuid,
        }

    def seed_private_boot(self, artifacts: Sequence[str]) -> dict[str, Any]:
        """Seed the candidate's private /boot from the exact live artifacts."""
        self.require_root()
        requested = tuple(artifacts)
        if len(requested) != len(set(requested)) or set(requested) != set(BOOT_ARTIFACTS):
            raise ValueError("candidate boot seed must bind the exact boot artifact set")
        if self._run(("mountpoint", "-q", str(self.offline_root))).returncode != 0:
            raise RuntimeError("normal candidate root is not mounted")
        private_boot = self.offline_root / "boot"
        if private_boot.is_symlink() or not private_boot.is_dir():
            raise RuntimeError("candidate private boot path is unsafe")

        hashes: dict[str, str] = {}
        sizes: dict[str, int] = {}
        for artifact in BOOT_ARTIFACTS:
            relative = Path(artifact).relative_to("/boot")
            live = self.boot_root / relative
            destination = private_boot / relative
            if live.is_symlink() or not live.is_file() or live.stat().st_size <= 0:
                raise RuntimeError(f"live boot seed artifact is unsafe: {artifact}")
            if destination.is_symlink() or (destination.exists() and not destination.is_file()):
                raise RuntimeError(f"candidate boot seed destination is unsafe: {artifact}")
            temporary = private_boot / f".maho-seed-{self.transaction_id}-{relative.name}.tmp"
            if temporary.exists() or temporary.is_symlink():
                raise RuntimeError(f"candidate boot seed temporary path exists: {artifact}")
            expected = sha256_file(live)
            shutil.copy2(live, temporary)
            try:
                if sha256_file(temporary) != expected:
                    raise RuntimeError(f"candidate boot seed hash mismatch: {artifact}")
                os.replace(temporary, destination)
            finally:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            hashes[artifact] = expected
            sizes[artifact] = destination.stat().st_size
        self._fsync_path(private_boot)
        return {"ok": True, "sha256": hashes, "size": sizes}

    def admission_roots(self, expected_candidate_uuid: str, expected_base_uuid: str) -> dict[str, Any]:
        self.require_root()
        self._unmount(self.offline_root)
        identity = self.root_identity()
        self._mount_top(identity)
        candidate = self.top / self.candidate
        base = self.top / self.admission_base
        if not candidate.exists() or not base.exists():
            raise RuntimeError("admission candidate/base topology is incomplete")
        candidate_uuid = self._show_uuid(candidate)
        base_uuid = self._show_uuid(base)
        candidate_read_only = self._read_only(candidate)
        base_read_only = self._read_only(base)
        if candidate_uuid != expected_candidate_uuid or not candidate_read_only:
            raise RuntimeError("admission candidate UUID drifted")
        if base_uuid != expected_base_uuid or not base_read_only:
            raise RuntimeError("admission base identity drifted")
        return {
            "base_root": str(base),
            "candidate_root": str(candidate),
            "candidate_uuid": candidate_uuid,
            "base_uuid": base_uuid,
            "candidate_read_only": candidate_read_only,
            "base_read_only": base_read_only,
        }

    def freeze_normal_candidate(self, expected_uuid: str) -> dict[str, Any]:
        """Freeze a non-boot candidate for stable Guardian admission."""
        self.require_root()
        self._unmount(self.offline_root)
        identity = self.root_identity()
        self._mount_top(identity)
        path = self.top / self.candidate
        if self._show_uuid(path) != expected_uuid:
            raise RuntimeError("normal candidate UUID drifted before freeze")
        self._set_read_only(path, True)
        if not self._read_only(path):
            raise RuntimeError("normal candidate did not become read-only")
        return {"read_only": True, "uuid": expected_uuid}

    def freeze_candidate(self, expected_uuid: str) -> dict[str, Any]:
        self.require_root()
        self._unmount(self.offline_root)
        identity = self.root_identity()
        self._mount_top(identity)
        path = self.top / self.candidate
        if self._show_uuid(path) != expected_uuid:
            raise RuntimeError("candidate UUID drifted before freeze")
        self._set_read_only(path, True)
        if not self._read_only(path):
            raise RuntimeError("candidate did not become read-only")
        hashes = self.private_boot_hashes(path)
        return {"read_only": True, "boot_sha256": hashes, "uuid": expected_uuid}

    def cleanup_candidate(self, expected_uuid: str) -> dict[str, Any]:
        self.require_root()
        # Recovery can be entered while the offline candidate still owns its
        # minimal /dev, /proc, /sys, and /run mounts. Tear those down before
        # attempting to unmount/delete the candidate root itself.
        self.unmount_normal_candidate_runtime()
        self._unmount(self.offline_root)
        identity = self.root_identity()
        self._mount_top(identity)
        path = self.top / self.candidate
        candidate_removed = not path.exists()
        if path.exists():
            if self._show_uuid(path) != expected_uuid:
                return {"ok": False, "reason": "candidate UUID drifted"}
            self._set_read_only(path, False)
            candidate_removed = self._run(("btrfs", "subvolume", "delete", str(path))).returncode == 0
        base = self.top / self.admission_base
        base_removed = not base.exists()
        if base.exists():
            self._set_read_only(base, False)
            base_removed = self._run(("btrfs", "subvolume", "delete", str(base))).returncode == 0
        return {
            "ok": candidate_removed and base_removed,
            "candidate_removed": candidate_removed,
            "admission_base_removed": base_removed,
        }

    def cleanup_admission_base(self, expected_uuid: str) -> dict[str, Any]:
        self.require_root()
        identity = self.root_identity()
        self._mount_top(identity)
        base = self.top / self.admission_base
        if not base.exists():
            return {"ok": True, "admission_base_removed": True, "already_absent": True}
        if self._show_uuid(base) != expected_uuid:
            return {"ok": False, "reason": "admission base UUID drifted"}
        self._set_read_only(base, False)
        removed = self._run(("btrfs", "subvolume", "delete", str(base))).returncode == 0
        return {"ok": removed, "admission_base_removed": removed}

    def read_previous_root_file(
        self,
        relative: str,
        *,
        expected_active_uuid: str | None = None,
    ) -> dict[str, Any]:
        """Read one bounded evidence file from the retained transaction backup root."""
        self.require_root()
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            raise ValueError("previous-root evidence path must be relative")
        parts = Path(relative).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("previous-root evidence path is unbounded")
        identity = self.root_identity()
        if expected_active_uuid is not None and identity.subvolume_uuid != expected_active_uuid:
            raise RuntimeError("active root is not the expected update candidate")
        self._mount_top(identity)
        previous = self.top / self.backup
        if not previous.exists() or not self._read_only(previous):
            raise RuntimeError("previous known-good root is absent or mutable")
        previous_uuid = self._show_uuid(previous)
        root = previous.resolve(strict=True)
        raw = previous
        for part in parts:
            raw = raw / part
            if raw.is_symlink():
                raise RuntimeError("previous-root evidence path contains a symlink")
        path = raw.resolve(strict=True)
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("previous-root evidence path escaped retained root") from exc
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("previous-root evidence is not a regular file")
        return {
            "content": path.read_bytes(),
            "previous_root_uuid": previous_uuid,
            "active_root_uuid": identity.subvolume_uuid,
            "relative_path": relative,
        }

    @staticmethod
    def _bounded_state_root(root: Path) -> Path:
        resolved_root = root.resolve(strict=True)
        path = root
        for part in ("var", "lib", "maho", "update"):
            path = path / part
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError("activation state root is unsafe")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise RuntimeError("activation state root escaped selected subvolume") from exc
        return resolved

    def activated_state_root(
        self,
        *,
        expected_candidate_uuid: str,
        expected_parent_root_uuid: str,
    ) -> Path:
        """Return state on the exact newly selected root after a completed arm."""
        if self.normal_activation_topology(
            expected_candidate_uuid=expected_candidate_uuid,
            expected_parent_root_uuid=expected_parent_root_uuid,
        ) != "ARMED":
            raise RuntimeError("normal activation is not durably armed")
        current = self.top / "@"
        return self._bounded_state_root(current)

    def prepared_candidate_state_root(
        self,
        *,
        expected_candidate_uuid: str,
        expected_parent_root_uuid: str,
    ) -> Path:
        """Return state inside the exact frozen candidate before exchange."""
        if self.normal_activation_topology(
            expected_candidate_uuid=expected_candidate_uuid,
            expected_parent_root_uuid=expected_parent_root_uuid,
        ) != "PREPARED":
            raise RuntimeError("normal activation candidate is not prepared")
        return self._bounded_state_root(self.top / self.candidate)

    def read_activation_source_file(
        self,
        relative: str,
        *,
        expected_active_uuid: str | None = None,
        expected_previous_uuid: str | None = None,
    ) -> dict[str, Any]:
        """Read handoff evidence across either post-exchange crash topology."""
        self.require_root()
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            raise ValueError("activation source evidence path must be relative")
        parts = Path(relative).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("activation source evidence path is unbounded")
        identity = self.root_identity()
        self._mount_top(identity)
        current = self.top / "@"
        candidate = self.top / self.candidate
        backup = self.top / self.backup
        if current.exists() and candidate.exists() and not backup.exists():
            source = self.top / self.candidate
            topology = "EXCHANGED_PENDING_BACKUP"
        elif current.exists() and backup.exists() and not candidate.exists():
            source = self.top / self.backup
            if not self._read_only(source):
                raise RuntimeError("previous known-good root is mutable")
            topology = "ARMED"
        else:
            raise RuntimeError("activation source topology is not recoverable")
        active_uuid = self._show_uuid(current)
        previous_uuid = self._show_uuid(source)
        if expected_active_uuid is not None and active_uuid != expected_active_uuid:
            raise RuntimeError("activation source active root UUID drifted")
        if expected_previous_uuid is not None and previous_uuid != expected_previous_uuid:
            raise RuntimeError("activation source root UUID drifted")
        source_root = source.resolve(strict=True)
        raw = source
        for part in parts:
            raw = raw / part
            if raw.is_symlink():
                raise RuntimeError("activation source evidence path contains a symlink")
        path = raw.resolve(strict=True)
        try:
            path.relative_to(source_root)
        except ValueError as exc:
            raise RuntimeError("activation source evidence path escaped retained root") from exc
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("activation source evidence is not a regular file")
        return {
            "content": path.read_bytes(),
            "previous_root_uuid": previous_uuid,
            "active_root_uuid": active_uuid,
            "relative_path": relative,
            "topology": topology,
        }

    def freeze_previous_root(self, previous_root_name: str, expected_uuid: str, active_candidate_uuid: str) -> dict[str, Any]:
        """Freeze the exact previous /@ only after the candidate is the live normal root."""
        self.require_root()
        if previous_root_name != self.backup:
            raise RuntimeError("previous-root backup name drifted")
        if _UUID.fullmatch(expected_uuid) is None or _UUID.fullmatch(active_candidate_uuid) is None:
            raise RuntimeError("previous-root or active candidate UUID is invalid")
        identity = self.root_identity()
        if identity.subvolume_uuid != active_candidate_uuid:
            raise RuntimeError("active /@ is not the exact M4B candidate")
        self._mount_top(identity)
        previous = self.top / previous_root_name
        if not previous.exists():
            raise FileNotFoundError("previous-root backup is missing")
        observed = self._show_uuid(previous)
        if observed != expected_uuid:
            raise RuntimeError("previous-root backup UUID drifted")
        self._set_read_only(previous, True)
        if not self._read_only(previous):
            raise RuntimeError("previous-root backup did not become read-only")
        return {"uuid": observed, "read_only": True, "name": previous_root_name}

    @staticmethod
    def private_boot_hashes(candidate_path: Path) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for artifact in BOOT_ARTIFACTS:
            path = candidate_path / artifact.lstrip("/")
            if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError(f"candidate boot artifact unavailable: {artifact}")
            hashes[artifact] = sha256_file(path)
        return hashes

    @staticmethod
    def _fsync_path(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _rename_exchange(first: Path, second: Path) -> None:
        """Atomically exchange two directory entries using renameat2(2)."""
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise RuntimeError("atomic rename exchange is unavailable")
        renameat2.argtypes = (
            ctypes.c_int, ctypes.c_char_p,
            ctypes.c_int, ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_exchange = 2
        result = renameat2(
            at_fdcwd, os.fsencode(first),
            at_fdcwd, os.fsencode(second),
            rename_exchange,
        )
        if result != 0:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err), f"{first} <-> {second}")

    def live_boot_hashes(self) -> dict[str, str]:
        hashes: dict[str, str] = {}
        for artifact in BOOT_ARTIFACTS:
            path = self.boot_root / Path(artifact).relative_to("/boot")
            if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
                raise RuntimeError(f"live boot artifact is unsafe: {artifact}")
            hashes[artifact] = sha256_file(path)
        return hashes

    def normal_activation_topology(
        self,
        *,
        expected_candidate_uuid: str,
        expected_parent_root_uuid: str,
    ) -> str:
        """Classify exact normal activation topology, including interruption states."""
        self.require_root()
        identity = self.root_identity()
        self._mount_top(identity)
        candidate = self.top / self.candidate
        current = self.top / "@"
        previous = self.top / self.backup
        if current.exists() and candidate.exists() and not previous.exists():
            current_uuid = self._show_uuid(current)
            candidate_uuid = self._show_uuid(candidate)
            if (
                current_uuid == expected_parent_root_uuid
                and candidate_uuid == expected_candidate_uuid
            ):
                return "PREPARED" if self._read_only(candidate) else "PREPARED_MUTABLE"
            if (
                current_uuid == expected_candidate_uuid
                and candidate_uuid == expected_parent_root_uuid
            ):
                return "EXCHANGED_PENDING_BACKUP"
            return "UNSAFE"
        if current.exists() and previous.exists() and not candidate.exists():
            if (
                self._show_uuid(current) == expected_candidate_uuid
                and self._show_uuid(previous) == expected_parent_root_uuid
                and not self._read_only(current)
                and self._read_only(previous)
            ):
                return "ARMED"
            return "UNSAFE"
        return "UNSAFE"

    def finalize_normal_activation_exchange(
        self,
        *,
        expected_candidate_uuid: str,
        expected_parent_root_uuid: str,
        expected_boot_hashes: Mapping[str, str],
    ) -> dict[str, Any]:
        """Finish the exact post-exchange/pre-backup crash topology."""
        self.require_root()
        identity = self.root_identity()
        self._mount_top(identity)
        candidate = self.top / self.candidate
        current = self.top / "@"
        previous = self.top / self.backup
        if (
            not current.exists() or not candidate.exists() or previous.exists()
            or self._show_uuid(current) != expected_candidate_uuid
            or self._show_uuid(candidate) != expected_parent_root_uuid
        ):
            raise RuntimeError("normal activation exchange topology is not exact")
        if self.live_boot_hashes() != dict(expected_boot_hashes):
            raise RuntimeError("normal activation boot identity drifted during exchange reconciliation")
        # Keep every crash point recognizable: the selected candidate becomes
        # writable only after the exchange, while the previous root is frozen
        # before its directory entry is renamed to the retained backup.
        self._set_read_only(current, False)
        self._set_read_only(candidate, True)
        if self._read_only(current) or not self._read_only(candidate):
            raise RuntimeError("normal activation exchange mutability reconciliation failed")
        os.rename(candidate, previous)
        self._fsync_path(self.top)
        if (
            self._show_uuid(previous) != expected_parent_root_uuid
            or not self._read_only(previous)
            or self._show_uuid(current) != expected_candidate_uuid
            or self._read_only(current)
        ):
            raise RuntimeError("normal activation exchange reconciliation failed")
        if self.live_boot_hashes() != dict(expected_boot_hashes):
            raise RuntimeError("normal activation unexpectedly changed boot artifacts")
        return {
            "candidate_uuid": expected_candidate_uuid,
            "previous_root_uuid": expected_parent_root_uuid,
            "previous_root_name": self.backup,
            "boot_sha256": dict(expected_boot_hashes),
            "boot_unchanged": True,
            "package_manager_invoked": False,
            "reboot_performed": False,
            "firmware_mutated": False,
            "reconciled_after_exchange_interruption": True,
        }

    def arm_root_activation(
        self,
        *,
        expected_candidate_uuid: str,
        expected_parent_root_uuid: str,
    ) -> dict[str, Any]:
        """Atomically select a frozen normal candidate as the next /@ root.

        No package command and no boot publication occurs here.  The previous
        known-good root is retained under the transaction-bound backup name.
        """
        self.require_root()
        if _UUID.fullmatch(expected_candidate_uuid) is None or _UUID.fullmatch(expected_parent_root_uuid) is None:
            raise ValueError("normal activation root identity is invalid")
        identity = self.root_identity()
        if identity.subvolume_uuid != expected_parent_root_uuid:
            raise RuntimeError("live root identity drifted before normal activation")
        self._mount_top(identity)
        candidate = self.top / self.candidate
        current = self.top / "@"
        previous = self.top / self.backup
        if not candidate.exists() or not current.exists() or previous.exists():
            raise RuntimeError("normal activation subvolume topology is not exact")
        if self._show_uuid(current) != expected_parent_root_uuid:
            raise RuntimeError("normal activation current root UUID drifted")
        if self._show_uuid(candidate) != expected_candidate_uuid or not self._read_only(candidate):
            raise RuntimeError("normal activation candidate is not the exact frozen subvolume")

        boot_before = self.live_boot_hashes()
        exchanged = False
        try:
            # The selected root must already be writable if power is lost just
            # after renameat2. If power is lost after this property change but
            # before exchange, topology reports PREPARED_MUTABLE and activation
            # fails closed rather than trusting the old frozen Admission proof.
            self._set_read_only(candidate, False)
            if self._read_only(candidate):
                raise RuntimeError("normal activation candidate did not become writable")
            self._rename_exchange(current, candidate)
            exchanged = True
            self._fsync_path(self.top)
            # After exchange, candidate-name holds the previous known-good root.
            if self._show_uuid(current) != expected_candidate_uuid:
                raise RuntimeError("normal activation exchange did not select exact candidate")
            if self._show_uuid(candidate) != expected_parent_root_uuid:
                raise RuntimeError("normal activation exchange lost previous root identity")
            # Freeze the previous root before renaming its directory entry so a
            # crash after retention can never leave a mutable recovery root.
            self._set_read_only(candidate, True)
            if self._read_only(current) or not self._read_only(candidate):
                raise RuntimeError("normal activation mutability transition failed")
            os.rename(candidate, previous)
            self._fsync_path(self.top)
            if (
                self._show_uuid(previous) != expected_parent_root_uuid
                or not self._read_only(previous)
                or self._read_only(current)
            ):
                raise RuntimeError("normal activation previous root preservation failed")
            boot_after = self.live_boot_hashes()
            if boot_after != boot_before:
                raise RuntimeError("normal activation unexpectedly changed boot artifacts")
        except Exception:
            # Best-effort rollback is safe only while the old root is still at
            # the transaction candidate name. Power-loss reconciliation is
            # handled by the durable activation handoff, not by blind replay.
            if exchanged and candidate.exists() and current.exists() and not previous.exists():
                try:
                    self._rename_exchange(current, candidate)
                    self._set_read_only(current, False)
                    self._set_read_only(candidate, True)
                except Exception:
                    pass
            elif candidate.exists() and not exchanged:
                try:
                    self._set_read_only(candidate, True)
                except Exception:
                    pass
            raise
        return {
            "candidate_uuid": expected_candidate_uuid,
            "previous_root_uuid": expected_parent_root_uuid,
            "previous_root_name": self.backup,
            "boot_sha256": boot_before,
            "boot_unchanged": True,
            "package_manager_invoked": False,
            "reboot_performed": False,
            "firmware_mutated": False,
        }

    def arm_activation(
        self,
        *,
        machine_id: str,
        expected_candidate_uuid: str,
        expected_boot_hashes: Mapping[str, str],
    ) -> dict[str, Any]:
        """Atomically make the frozen candidate the next /@ and publish boot files."""
        self.require_root()
        identity = self.root_identity()
        self._mount_top(identity)
        candidate = self.top / self.candidate
        current = self.top / "@"
        previous = self.top / self.backup
        if not candidate.exists() or not current.exists() or previous.exists():
            raise RuntimeError("activation subvolume topology is not exact")
        if self._show_uuid(candidate) != expected_candidate_uuid or not self._read_only(candidate):
            raise RuntimeError("activation candidate is not the exact frozen subvolume")
        observed_hashes = self.private_boot_hashes(candidate)
        if dict(expected_boot_hashes) != observed_hashes:
            raise RuntimeError("candidate boot hashes drifted before activation")

        backup_dir = self.boot_root / machine_id / "maho" / "update" / "backups" / self.transaction_id
        backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        boot_backups: dict[str, str] = {}
        temps: dict[str, Path] = {}
        for artifact in BOOT_ARTIFACTS:
            live = self.boot_root / Path(artifact).relative_to("/boot")
            if live.is_symlink() or not live.is_file() or live.stat().st_size <= 0:
                raise RuntimeError(f"live boot artifact is unsafe: {artifact}")
            backup = backup_dir / live.name
            shutil.copy2(live, backup)
            boot_backups[artifact] = sha256_file(backup)
            temporary = live.parent / f".maho-m4b-{self.transaction_id}-{live.name}.tmp"
            if temporary.exists():
                temporary.unlink()
            shutil.copy2(candidate / artifact.lstrip("/"), temporary)
            if sha256_file(temporary) != expected_boot_hashes[artifact]:
                raise RuntimeError(f"temporary boot artifact hash mismatch: {artifact}")
            temps[artifact] = temporary
        (backup_dir / "manifest.json").write_text(
            json.dumps({"sha256": boot_backups}, sort_keys=True) + "\n", encoding="utf-8"
        )
        self._fsync_path(backup_dir)

        swapped = False
        published: list[str] = []
        try:
            self._set_read_only(candidate, False)
            os.rename(current, previous)
            try:
                os.rename(candidate, current)
            except Exception:
                os.rename(previous, current)
                self._set_read_only(candidate, True)
                raise
            swapped = True
            for artifact in BOOT_ARTIFACTS:
                os.replace(temps[artifact], self.boot_root / Path(artifact).relative_to("/boot"))
                published.append(artifact)
            self._fsync_path(self.boot_root)
            if self._show_uuid(current) != expected_candidate_uuid:
                raise RuntimeError("activated /@ UUID does not match candidate")
            for artifact in BOOT_ARTIFACTS:
                if sha256_file(self.boot_root / Path(artifact).relative_to("/boot")) != expected_boot_hashes[artifact]:
                    raise RuntimeError(f"published boot artifact hash mismatch: {artifact}")
        except Exception:
            for artifact in published:
                backup = backup_dir / Path(artifact).name
                if backup.is_file():
                    shutil.copy2(backup, self.boot_root / Path(artifact).relative_to("/boot"))
            for temporary in temps.values():
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
            if swapped:
                failed_candidate = self.top / self.candidate
                os.rename(current, failed_candidate)
                os.rename(previous, current)
                self._set_read_only(failed_candidate, True)
            else:
                # Mutation may have stopped after thawing but before the rename.
                # Never leave the prepared candidate writable on a failed arm.
                candidate_after_failure = self.top / self.candidate
                if candidate_after_failure.exists():
                    try:
                        self._set_read_only(candidate_after_failure, True)
                    except Exception:
                        pass
            self._fsync_path(self.boot_root)
            # A failed pre-swap arm has no durable value; remove its boot backup
            # directory so the same exact transaction can be retried safely.
            if not swapped:
                shutil.rmtree(backup_dir, ignore_errors=True)
            raise
        return {
            "candidate_uuid": expected_candidate_uuid,
            "previous_root_uuid": identity.subvolume_uuid,
            "previous_root_name": self.backup,
            "boot_backup_dir": str(backup_dir),
            "boot_sha256": dict(expected_boot_hashes),
            "reboot_performed": False,
            "firmware_mutated": False,
        }


class NativeCandidateUpdateOps(OfflineRootUpdateOps):
    """M4A executor bound to one M4B candidate subvolume and one M3B target."""

    production_safe = True
    PACMAN_CONFIG = "/etc/maho/pacman.conf"

    def __init__(
        self,
        offline_root: str | os.PathLike[str],
        cache_root: str | os.PathLike[str],
        *,
        transaction: Mapping[str, Any],
        expected_versions: Mapping[str, str],
        runtime_user: str,
        runtime_identity: Mapping[str, Any],
        recovery_seed: Mapping[str, Any],
        recovery_journal_path: str | os.PathLike[str],
        machine_id: str,
        candidate_uuid: str,
        btrfs_ops: NativeBtrfsOps,
        runner=None,
    ) -> None:
        super().__init__(offline_root, cache_root, runner=runner)
        self.transaction = dict(transaction)
        self.expected_versions = dict(expected_versions)
        self.runtime_user = runtime_user
        self.runtime_identity = dict(runtime_identity)
        self.recovery_seed = dict(recovery_seed)
        self.recovery_journal_path = Path(recovery_journal_path)
        self.machine_id = machine_id
        self.candidate_uuid = candidate_uuid
        self.btrfs_ops = btrfs_ops

    def _sysroot_prefix(self) -> tuple[str, ...]:
        config = self.root / self.PACMAN_CONFIG.lstrip("/")
        if config.is_symlink() or not config.is_file():
            raise ValueError("candidate Maho Pacman config is unavailable")
        return (self.PACMAN, "--sysroot", str(self.root), "--config", self.PACMAN_CONFIG)

    def install_command(self, plan: ExecutionPlan) -> tuple[str, ...]:
        payloads = tuple(str(Path(path).resolve(strict=False)) for path in plan.payload_paths)
        if not payloads or any(Path(path).parent != self.cache for path in payloads):
            raise ValueError("offline install payload escapes isolated cache")
        return (
            *self._sysroot_prefix(),
            "--upgrade", "--noconfirm", "--needed", "--", *payloads,
        )

    def query_command(self, plan: ExecutionPlan) -> tuple[str, ...]:
        names = tuple(sorted(self.expected_versions))
        if not names or any(_PACKAGE.fullmatch(name) is None for name in names):
            raise ValueError("candidate package verification set is invalid")
        return (*self._sysroot_prefix(), "--query", "--", *names)

    def prepare_recovery(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        if plan.recovery_generation_id != self.recovery_seed.get("generation_id"):
            return {"ok": False, "reason": "recovery generation mismatch"}
        journal = read_journal(self.recovery_journal_path)
        if journal.get("phase") != "prepared":
            return {"ok": False, "reason": "M3B recovery transaction is not prepared"}
        sid = self.recovery_seed.get("snapshot_id")
        host = SystemPreparationOps(machine_id=self.machine_id)
        evidence = host.wait_for_backup(int(sid))
        ok = (
            evidence.get("snapshot_uuid") == self.recovery_seed.get("snapshot_uuid")
            and evidence.get("read_only") is True
            and evidence.get("boot_state_coherent") is True
            and evidence.get("files_verified") is True
        )
        return {"ok": ok, "generation_id": plan.recovery_generation_id, "snapshot_id": sid}

    def verify_maho_runtime(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        base = Path("/home") / self.runtime_user / ".local/share/maho/runtime"
        verification = verify_release(base / "current", base / "releases")
        ok = (
            verification.verified
            and verification.content_sha256 == plan.maho_runtime.get("version")
            and verification.source_revision == plan.maho_runtime.get("source_revision")
        )
        return {"ok": ok, "verification": verification.as_dict()}

    def verify_kernel_matrix(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        result = self.run(self.query_command(plan), plan)
        observed: dict[str, str] = {}
        for line in result.stdout.splitlines():
            name, separator, version = line.partition(" ")
            if separator:
                observed[name] = version.strip()
        ok = result.returncode == 0 and all(observed.get(name) == version for name, version in self.expected_versions.items())
        evidence = {"ok": ok, "observed": observed, "expected": self.expected_versions}
        if result.returncode != 0:
            evidence["failure_evidence"] = self._failure_evidence("kernel-header-dkms", result)
        return evidence

    def finalize_install(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        shown = self.btrfs_ops._run(("btrfs", "subvolume", "show", str(self.root)), check=True)
        observed = _subvolume_field(shown.stdout, "UUID")
        return {
            "ok": observed == self.candidate_uuid,
            "candidate_uuid": observed,
            "activation_required": list(plan.activation_requirements),
        }

    def recover(self, plan: ExecutionPlan, failed_stage: str) -> Mapping[str, Any]:
        # The disposable candidate *is* the rollback boundary. The durable update
        # journal lives on the still-running root, so it remains writable while
        # this cleanup removes every partial candidate mutation.
        result = self.btrfs_ops.cleanup_candidate(self.candidate_uuid)
        return {**result, "failed_stage": failed_stage, "live_root_untouched": True}


class PostBootActivationOps:
    """Post-reboot verifier/finalizer for the activated M4B candidate."""

    production_safe = True
    fixture_safe = False

    def __init__(
        self,
        *,
        transaction: Mapping[str, Any],
        expected_versions: Mapping[str, str],
        runtime_user: str,
        home_identity: Mapping[str, str],
        runtime_identity: Mapping[str, Any],
        candidate_uuid: str,
        previous_root_uuid: str,
        previous_root_name: str,
        boot_hashes: Mapping[str, str],
        recovery_seed: Mapping[str, Any],
        machine_id: str,
    ) -> None:
        self.transaction = dict(transaction)
        self.expected_versions = dict(expected_versions)
        self.runtime_user = runtime_user
        self.home_identity = dict(home_identity)
        self.runtime_identity = dict(runtime_identity)
        self.candidate_uuid = candidate_uuid
        self.previous_root_uuid = previous_root_uuid
        self.previous_root_name = previous_root_name
        self.boot_hashes = dict(boot_hashes)
        self.recovery_seed = dict(recovery_seed)
        self.machine_id = machine_id

    @staticmethod
    def _run(command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(list(command), check=False, text=True, capture_output=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)

    def verify_activation(self, plan: ExecutionPlan) -> Mapping[str, Any]:
        blockers: list[str] = []
        cmdline = Path("/proc/cmdline").read_text(encoding="utf-8").split()
        if "maho.recovery_snapshot=1" in cmdline:
            blockers.append("recovery_boot_still_active")
        mount = self._run(("findmnt", "--json", "--target", "/", "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID"))
        try:
            row = json.loads(mount.stdout)["filesystems"][0]
        except Exception:
            row = {}
        if row.get("fstype") != "btrfs" or row.get("fsroot") != "/@":
            blockers.append("activated_root_is_not_normal_at")
        shown = self._run(("btrfs", "subvolume", "show", "/"))
        root_uuid = _subvolume_field(shown.stdout, "UUID") if shown.returncode == 0 else None
        if root_uuid != self.candidate_uuid:
            blockers.append("activated_root_uuid_mismatch")

        package_names = tuple(sorted(self.expected_versions))
        packages = self._run(("pacman", "-Q", *package_names)) if package_names else CommandResult(1, "", "")
        observed: dict[str, str] = {}
        for line in packages.stdout.splitlines():
            name, separator, version = line.partition(" ")
            if separator:
                observed[name] = version.strip()
        if packages.returncode != 0 or any(observed.get(name) != version for name, version in self.expected_versions.items()):
            blockers.append("activated_package_generation_mismatch")

        primary_version = self.expected_versions.get("linux-cachyos")
        running = os.uname().release
        if primary_version and running != f"{primary_version}-cachyos":
            blockers.append("running_primary_kernel_mismatch")
        for artifact, expected in self.boot_hashes.items():
            path = Path(artifact)
            if not path.is_file() or sha256_file(path) != expected:
                blockers.append("published_boot_artifact_mismatch")
                break

        host = SystemPreparationOps(machine_id=self.machine_id)
        if host.home_identity() != self.home_identity:
            blockers.append("home_identity_changed")
        base = Path("/home") / self.runtime_user / ".local/share/maho/runtime"
        runtime = verify_release(base / "current", base / "releases")
        if not runtime.verified or runtime.content_sha256 != plan.maho_runtime.get("version") or runtime.source_revision != plan.maho_runtime.get("source_revision"):
            blockers.append("maho_runtime_identity_changed")
        recovery = host.wait_for_backup(int(self.recovery_seed["snapshot_id"]))
        if recovery.get("snapshot_uuid") != self.recovery_seed.get("snapshot_uuid") or recovery.get("read_only") is not True:
            blockers.append("m3b_recovery_generation_lost")

        previous_uuid = None
        previous_read_only = False
        activation_identity_proven = candidate_boot_proven(cmdline, row, root_uuid, self.candidate_uuid)
        if activation_identity_proven:
            btrfs = NativeBtrfsOps(self.transaction["transaction_id"])
            try:
                frozen = btrfs.freeze_previous_root(self.previous_root_name, self.previous_root_uuid, self.candidate_uuid)
                previous_uuid = frozen["uuid"]
                previous_read_only = frozen["read_only"] is True
            except FileNotFoundError:
                blockers.append("previous_root_backup_missing")
            except Exception:
                blockers.append("previous_root_backup_not_immutable")
            finally:
                btrfs.close()
        if activation_identity_proven and previous_uuid != self.previous_root_uuid and "previous_root_backup_missing" not in blockers:
            blockers.append("previous_root_backup_missing")
        if activation_identity_proven and previous_uuid == self.previous_root_uuid and not previous_read_only:
            blockers.append("previous_root_backup_not_immutable")
        return {
            "ok": not blockers,
            "blockers": blockers,
            "root_uuid": root_uuid,
            "package_versions": observed,
            "running_kernel": running,
            "home_preserved": not any(item == "home_identity_changed" for item in blockers),
            "runtime": runtime.as_dict(),
            "recovery_generation_id": plan.recovery_generation_id,
            "previous_root_uuid": previous_uuid,
            "previous_root_read_only": previous_read_only,
        }

    # The remaining protocol methods are deliberately unavailable post-boot.
    def prepare_recovery(self, plan): raise RuntimeError("postboot verifier cannot prepare recovery")
    def install_full_upgrade(self, plan): raise RuntimeError("postboot verifier cannot install")
    def verify_maho_runtime(self, plan): raise RuntimeError("use verify_activation")
    def verify_kernel_matrix(self, plan): raise RuntimeError("use verify_activation")
    def build_initramfs(self, plan, preset): raise RuntimeError("postboot verifier cannot build initramfs")
    def verify_boot_artifacts(self, plan): raise RuntimeError("use verify_activation")
    def finalize_install(self, plan): raise RuntimeError("postboot verifier cannot finalize")
    def recover(self, plan, failed_stage): return {"ok": False, "reason": "postboot recovery requires M3B recovery boot"}
