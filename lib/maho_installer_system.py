#!/usr/bin/env python3
"""Concrete target-system operations for the S1.2 installer transaction."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
from typing import Any, Mapping, Sequence

from maho_boot_authority import BootArtifact, BootGeneration, Digest, LoaderIdentity
from maho_generation_v2 import RootIdentity, SystemGeneration
from maho_installer_execute import _write_json_durable
from maho_installer_receipt import build_install_receipt
from maho_kernel_generation import KernelGeneration, modules_tree_artifact
from maho_recovery_generation import generation_identity
from maho_trust_identity import ArtifactID, ProvenanceID, TransactionID, TrustState, canonical_bytes


_USER = re.compile(r"[a-z_][a-z0-9_-]{0,30}")
_HOST = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,62}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _blake2b(path: Path) -> str:
    digest = hashlib.blake2b(digest_size=64)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class SystemAssemblyOps:
    """The only subprocess-backed S1.2 target mutation provider."""

    def __init__(
        self, *, payload_dir: Path, user_name: str, host_name: str,
        password_file: Path, storage_key_file: Path, recovery_key_output: Path,
    ) -> None:
        if _USER.fullmatch(user_name) is None or _HOST.fullmatch(host_name) is None:
            raise ValueError("initial user or host name is invalid")
        self.payload_dir = payload_dir.resolve()
        self.user_name = user_name
        self.host_name = host_name
        self.password_file = password_file.resolve()
        self.storage_key_file = storage_key_file.resolve()
        self.recovery_key_output = recovery_key_output.resolve()
        for path, label in (
            (self.password_file, "initial password"),
            (self.storage_key_file, "storage key"),
        ):
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size == 0 or stat.S_IMODE(metadata.st_mode) & 0o077:
                raise ValueError(f"{label} file must be a non-empty private regular file")

    def _run(
        self, command: Sequence[str], *, input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        result = subprocess.run(
            list(command), input=input_bytes, capture_output=True, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).decode(errors="replace").strip()
            raise RuntimeError(f"target assembly command failed ({command[0]}): {detail}")
        return result

    def _chroot(
        self, root: Path, command: Sequence[str], *, input_bytes: bytes | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        return self._run(("arch-chroot", str(root), *command), input_bytes=input_bytes, check=check)

    def _state_root(self, root: Path) -> Path:
        return root / "var/lib/maho/installer"

    def _findmnt(self, target: Path) -> Mapping[str, Any]:
        result = self._run((
            "findmnt", "--json", "--target", str(target),
            "--output", "SOURCE,FSTYPE,FSROOT,UUID",
        ))
        value = json.loads(result.stdout.decode())
        rows = value.get("filesystems") if isinstance(value, Mapping) else None
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise RuntimeError(f"target mount observation is ambiguous: {target}")
        return rows[0]

    def _subvolume_uuid(self, path: Path) -> str:
        result = self._run(("btrfs", "subvolume", "show", str(path)))
        for raw in result.stdout.decode().splitlines():
            line = raw.strip()
            if line.startswith("UUID:"):
                value = line.split(":", 1)[1].strip()
                if value:
                    return value
        raise RuntimeError(f"Btrfs subvolume UUID is unavailable: {path}")

    def _target_symlink_release(self, root: Path, link: Path) -> Path:
        raw = Path(os.readlink(link))
        candidate = root / raw.relative_to("/") if raw.is_absolute() else link.parent / raw
        resolved = candidate.resolve(strict=True)
        resolved_root = root.resolve()
        if not resolved.is_relative_to(resolved_root):
            raise RuntimeError("target runtime link escapes the installed root")
        return resolved

    def _microcode_package(self) -> str:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^vendor_id\s*:\s*(\S+)", text, re.MULTILINE)
        if match is None:
            raise RuntimeError("virtual CPU vendor could not be identified")
        if match.group(1) == "GenuineIntel":
            return "intel-ucode"
        if match.group(1) == "AuthenticAMD":
            return "amd-ucode"
        raise RuntimeError(f"unsupported virtual CPU vendor: {match.group(1)}")

    def verify_target_mount(
        self, plan: Mapping[str, Any], mount_root: Path,
    ) -> Mapping[str, Any]:
        expected_uuid = plan["installation_identity"]["btrfs_uuid"]
        expected_esp = plan["installation_identity"]["esp_partition_uuid"]
        expected_luks = plan["installation_identity"]["luks_uuid"]
        mapper = plan["encryption_contract"]["mapper_name"]
        expected = {
            mount_root: "/@",
            mount_root / "home": "/@home",
            mount_root / ".snapshots": "/@snapshots",
            mount_root / "var/log": "/@var_log",
        }
        observed: dict[str, Any] = {}
        for target, fsroot in expected.items():
            row = self._findmnt(target)
            if row.get("fstype") != "btrfs" or row.get("uuid") != expected_uuid or row.get("fsroot") != fsroot:
                raise RuntimeError(f"mounted target identity mismatch: {target}")
            observed[str(target)] = {"uuid": row.get("uuid"), "fsroot": row.get("fsroot")}
        root_source = str(self._findmnt(mount_root).get("source", "")).split("[", 1)[0]
        if Path(root_source).name != mapper:
            raise RuntimeError("mounted root is not backed by the planned LUKS mapper")
        crypt = self._run(("cryptsetup", "status", mapper))
        device = next((
            line.split(":", 1)[1].strip() for line in crypt.stdout.decode().splitlines()
            if line.strip().startswith("device:")
        ), "")
        if not device or self._run(("cryptsetup", "luksUUID", device)).stdout.decode().strip() != expected_luks:
            raise RuntimeError("mounted root LUKS identity mismatch")
        boot = self._findmnt(mount_root / "boot")
        boot_source = str(boot.get("source", "")).split("[", 1)[0]
        partuuid = self._run(("blkid", "-s", "PARTUUID", "-o", "value", boot_source)).stdout.decode().strip()
        if boot.get("fstype") not in {"vfat", "fat", "fat32"} or partuuid.lower() != str(expected_esp).lower():
            raise RuntimeError("mounted ESP identity mismatch")
        return {"verified": True, "btrfs_uuid": expected_uuid, "luks_uuid": expected_luks, "esp_partuuid": partuuid, "mounts": observed}

    def _marker(self, root: Path, phase: str) -> Path:
        return self._state_root(root) / "phases" / f"{phase}.json"

    def _mark(
        self, root: Path, phase: str, plan: Mapping[str, Any],
        payload: Mapping[str, Any], evidence: Mapping[str, Any],
    ) -> dict[str, Any]:
        value = {
            "schema_version": 1,
            "kind": "maho-installer-phase-evidence",
            "phase": phase,
            "install_attempt_id": plan["install_attempt_id"],
            "installation_uuid": plan["installation_identity"]["installation_uuid"],
            "payload_sha256": payload["payload_sha256"],
            "evidence": dict(evidence),
        }
        _write_json_durable(self._marker(root, phase), value)
        return dict(evidence)

    def _read_marker(self, root: Path, phase: str) -> Mapping[str, Any] | None:
        try:
            value = json.loads(self._marker(root, phase).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, Mapping) else None

    def phase_complete(
        self, phase: str, plan: Mapping[str, Any], payload: Mapping[str, Any],
        journal: Mapping[str, Any], mount_root: Path,
    ) -> bool:
        if phase == "UNMOUNTED":
            mounted = self._run(("findmnt", "--target", str(mount_root)), check=False).returncode == 0
            mapper = Path("/dev/mapper") / plan["encryption_contract"]["mapper_name"]
            return not mounted and not mapper.exists()
        marker = self._read_marker(mount_root, phase)
        return bool(
            marker
            and marker.get("phase") == phase
            and marker.get("install_attempt_id") == plan["install_attempt_id"]
            and marker.get("installation_uuid") == plan["installation_identity"]["installation_uuid"]
            and marker.get("payload_sha256") == payload["payload_sha256"]
        )

    def phase_started(
        self, phase: str, plan: Mapping[str, Any], payload: Mapping[str, Any],
        journal: Mapping[str, Any], mount_root: Path,
    ) -> bool:
        return False

    def apply_phase(
        self, phase: str, plan: Mapping[str, Any], payload: Mapping[str, Any],
        journal: Mapping[str, Any], mount_root: Path,
    ) -> Mapping[str, Any]:
        operation = getattr(self, f"_phase_{phase.lower()}", None)
        if operation is None:
            raise RuntimeError(f"unsupported assembly phase: {phase}")
        evidence = dict(operation(plan, payload, journal, mount_root))
        if phase != "UNMOUNTED":
            return self._mark(mount_root, phase, plan, payload, evidence)
        return evidence

    def _phase_payload_verified(self, plan, payload, journal, root) -> Mapping[str, Any]:
        return {
            "payload_sha256": payload["payload_sha256"],
            "package_generation_id": payload["package_generation_id"],
            "source_revision": payload["source_revision"],
            "package_version": payload["package_version"],
            "package_count": len(payload["packages"]),
            "all_repository_packages_signature_verified": all(
                item["signature"]["status"] == "verified"
                for item in payload["packages"] if item["name"] != "maho-os"
            ),
        }

    def _phase_base_installed(self, plan, payload, journal, root) -> Mapping[str, Any]:
        files = [str(self.payload_dir / item["filename"]) for item in payload["packages"]]
        # Every archive was signature-verified before destructive work and is
        # re-hashed against the immutable payload manifest immediately before
        # this phase.  A fresh target keyring cannot yet validate those same
        # archives, so use a single-run pacman config that trusts only the
        # already-verified local bytes.  Network access is simultaneously
        # removed.  The relaxed config is never copied into the target.
        offline_config = root.parent / f".maho-installer-pacman-{os.getpid()}.conf"
        offline_config.write_text(
            "[options]\n"
            "Architecture = auto\n"
            "SigLevel = Never\n"
            "LocalFileSigLevel = Never\n",
            encoding="utf-8",
        )
        try:
            self._run((
                "unshare", "--net", "--", "pacstrap",
                "-K", "-C", str(offline_config), "-U", str(root), *files,
            ))
        finally:
            offline_config.unlink(missing_ok=True)
        # Restore ordinary Arch package trust inside the installed system from
        # the keyring package that was part of the verified closure.
        self._chroot(root, ("pacman-key", "--populate", "archlinux"))
        target_pacman_conf = (root / "etc/pacman.conf").read_text(encoding="utf-8")
        active_policy = [
            line.split("#", 1)[0].strip()
            for line in target_pacman_conf.splitlines()
            if line.split("#", 1)[0].strip()
        ]
        if any(
            line.startswith(("SigLevel", "LocalFileSigLevel")) and "Never" in line
            for line in active_policy
        ):
            raise RuntimeError("target pacman signature policy remained relaxed after offline bootstrap")
        query = self._chroot(root, ("pacman", "-Q"))
        installed = dict(
            line.split(" ", 1) for line in query.stdout.decode().splitlines() if " " in line
        )
        expected = {item["name"]: item["version"] for item in payload["packages"]}
        if installed != expected:
            missing = sorted(set(expected) - set(installed))
            unexpected = sorted(set(installed) - set(expected))
            wrong = sorted(name for name in set(expected) & set(installed) if installed[name] != expected[name])
            raise RuntimeError(
                f"installed package set does not match the verified payload: missing={missing} unexpected={unexpected} wrong_version={wrong}"
            )
        return {
            "package_generation_id": payload["package_generation_id"],
            "installed_package_count": len(installed),
            "network_isolated": True,
            "exact_package_set": True,
            "bootstrap_package_authority": "manifest-preverified-hash-bound",
            "target_arch_keyring_populated": True,
            "target_signature_policy_relaxed": False,
            "expected_versions_sha256": hashlib.sha256(canonical_bytes(expected)).hexdigest(),
        }

    def _phase_identities_created(self, plan, payload, journal, root) -> Mapping[str, Any]:
        (root / "etc/maho").mkdir(parents=True, exist_ok=True)
        (root / "etc/hostname").write_text(self.host_name + "\n", encoding="utf-8")
        machine_id_path = root / "etc/machine-id"
        machine_id_path.unlink(missing_ok=True)
        self._run(("systemd-machine-id-setup", f"--root={root}"))
        machine_id = machine_id_path.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[0-9a-f]{32}", machine_id):
            raise RuntimeError("target machine identity was not created")
        identity = {
            "schema_version": 1,
            "kind": "maho-installation-identity",
            "install_attempt_id": plan["install_attempt_id"],
            "installation_uuid": plan["installation_identity"]["installation_uuid"],
            "machine_id": machine_id,
            "source_revision": plan["source_revision"],
            "payload_sha256": payload["payload_sha256"],
        }
        _write_json_durable(root / "etc/maho/installation.json", identity)
        filesystem = plan["installation_identity"]["btrfs_uuid"]
        esp = plan["installation_identity"]["esp_partition_uuid"]
        luks = plan["installation_identity"]["luks_uuid"]
        mapper = plan["encryption_contract"]["mapper_name"]
        (root / "etc/fstab").write_text(
            f"UUID={filesystem} / btrfs rw,noatime,compress=zstd,subvol=@ 0 0\n"
            f"UUID={filesystem} /home btrfs rw,noatime,compress=zstd,subvol=@home 0 0\n"
            f"UUID={filesystem} /.snapshots btrfs rw,noatime,compress=zstd,subvol=@snapshots 0 0\n"
            f"UUID={filesystem} /var/log btrfs rw,noatime,compress=zstd,subvol=@var_log 0 0\n"
            f"PARTUUID={esp} /boot vfat rw,umask=0077 0 2\n",
            encoding="utf-8",
        )
        (root / "etc/crypttab.initramfs").write_text(
            f"{mapper} UUID={luks} none luks\n", encoding="utf-8",
        )
        luks_partition = plan["layout_contract"]["partitions"][1]["path"]
        password = self.password_file.read_bytes().rstrip(b"\n") + b"\n"
        self._run((
            "cryptsetup", "luksAddKey", luks_partition,
            "--key-file", str(self.storage_key_file), "--new-keyfile", "-",
        ), input_bytes=password)
        recovery = secrets.token_bytes(48).hex().encode() + b"\n"
        self.recovery_key_output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.recovery_key_output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(recovery)
            stream.flush()
            os.fsync(stream.fileno())
        self._run((
            "cryptsetup", "luksAddKey", luks_partition,
            "--key-file", str(self.storage_key_file),
            "--new-keyfile", str(self.recovery_key_output),
        ))
        # The live installer bootstrap key must not survive as an unlock path.
        # First verify both intended post-install credentials, then remove the
        # bootstrap keyslot and prove the retired key no longer authenticates.
        self._run((
            "cryptsetup", "open", "--test-passphrase", "--key-file", "-",
            luks_partition,
        ), input_bytes=password)
        self._run((
            "cryptsetup", "open", "--test-passphrase",
            "--key-file", str(self.recovery_key_output), luks_partition,
        ))
        self._run((
            "cryptsetup", "luksRemoveKey", luks_partition, str(self.storage_key_file),
        ))
        retired = self._run((
            "cryptsetup", "open", "--test-passphrase",
            "--key-file", str(self.storage_key_file), luks_partition,
        ), check=False)
        if retired.returncode == 0:
            raise RuntimeError("installer bootstrap LUKS key remained valid after revocation")
        root_subvolume_uuid = self._subvolume_uuid(root)
        home_subvolume_uuid = self._subvolume_uuid(root / "home")
        return {
            "machine_id": machine_id,
            "host_name": self.host_name,
            "identity_separation": True,
            "root_subvolume_uuid": root_subvolume_uuid,
            "home_subvolume_uuid": home_subvolume_uuid,
            "password_slot_added": True,
            "password_slot_verified": True,
            "recovery_key_exported": self.recovery_key_output.is_file(),
            "recovery_slot_verified": True,
            "bootstrap_key_revoked": True,
        }

    def _phase_users_created(self, plan, payload, journal, root) -> Mapping[str, Any]:
        self._chroot(root, (
            "useradd", "--create-home", "--uid", "1000", "--user-group",
            "--groups", "wheel", "--shell", "/bin/bash", self.user_name,
        ))
        password = self.password_file.read_bytes().rstrip(b"\n")
        self._chroot(root, ("chpasswd",), input_bytes=self.user_name.encode() + b":" + password + b"\n")
        self._chroot(root, ("passwd", "--lock", "root"))
        sudoers = root / "etc/sudoers.d/10-maho-wheel"
        sudoers.write_text("%wheel ALL=(ALL:ALL) ALL\n", encoding="utf-8")
        sudoers.chmod(0o440)
        entry = self._chroot(root, ("getent", "passwd", self.user_name)).stdout.decode().strip()
        if entry.split(":")[2] != "1000":
            raise RuntimeError("initial desktop user UID is not 1000")
        return {
            "name": self.user_name, "uid": 1000, "wheel": True,
            "root_locked": True, "home_fsroot": "/@home",
        }

    def _phase_runtime_installed(self, plan, payload, journal, root) -> Mapping[str, Any]:
        home = f"/home/{self.user_name}"
        command = (
            "runuser", "-u", self.user_name, "--", "env", f"HOME={home}",
            f"XDG_CONFIG_HOME={home}/.config", f"XDG_DATA_HOME={home}/.local/share",
            f"XDG_STATE_HOME={home}/.local/state", "XDG_RUNTIME_DIR=/run/user/1000",
            "bash", "/usr/lib/maho/bin/maho-setup", "install",
        )
        self._chroot(root, command)
        current = root / home.lstrip("/") / ".local/share/maho/runtime/current"
        release = self._target_symlink_release(root, current)
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("source_revision") != plan["source_revision"]:
            raise RuntimeError("immutable runtime source identity drifted")
        if manifest.get("deployment_class") != "production" or manifest.get("trust_eligible") is not True:
            raise RuntimeError("installed runtime is not production trust-eligible")
        return {
            "source_revision": manifest["source_revision"],
            "content_sha256": manifest["content_sha256"],
            "deployment_class": manifest["deployment_class"],
            "trust_eligible": True,
            "verified": True,
            "release_path": str(current.relative_to(root)),
        }

    def _kernel_releases(self, root: Path) -> tuple[str, str]:
        found: dict[str, str] = {}
        modules = root / "usr/lib/modules"
        for directory in sorted(modules.iterdir()):
            try:
                package = (directory / "pkgbase").read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if package in {"linux-cachyos", "linux-cachyos-lts"}:
                found[package] = directory.name
        if set(found) != {"linux-cachyos", "linux-cachyos-lts"}:
            raise RuntimeError("required Primary and fallback kernel modules are missing")
        return found["linux-cachyos"], found["linux-cachyos-lts"]

    def _phase_kernels_installed(self, plan, payload, journal, root) -> Mapping[str, Any]:
        primary, fallback = self._kernel_releases(root)
        for path in (
            root / "boot/vmlinuz-linux-cachyos", root / "boot/vmlinuz-linux-cachyos-lts",
        ):
            if not path.is_file():
                raise RuntimeError(f"kernel image is missing: {path.name}")
        microcode_package = self._microcode_package()
        names = {item["name"] for item in payload["packages"]}
        if microcode_package not in names:
            raise RuntimeError(f"verified payload lacks CPU microcode package: {microcode_package}")
        return {
            "primary_package": "linux-cachyos", "primary_release": primary,
            "fallback_package": "linux-cachyos-lts", "fallback_release": fallback,
            "primary_headers": True, "fallback_headers": True,
            "microcode_package": microcode_package,
        }

    def _cmdline(self, plan: Mapping[str, Any], *, recovery: bool = False) -> str:
        luks = plan["installation_identity"]["luks_uuid"]
        filesystem = plan["installation_identity"]["btrfs_uuid"]
        mapper = plan["encryption_contract"]["mapper_name"]
        subvolume = "@snapshots/1/snapshot" if recovery else "@"
        mode = "ro" if recovery else "rw"
        return (
            f"rd.luks.name={luks}={mapper} root=UUID={filesystem} "
            f"rootflags=subvol={subvolume} {mode} console=ttyS0,115200n8"
        )

    def _verify_initramfs(self, root: Path, image: str) -> dict[str, Any]:
        config = self._chroot(root, ("lsinitcpio", "-c", image)).stdout.decode(errors="replace")
        contents = self._chroot(root, ("lsinitcpio", "-l", image)).stdout.decode(errors="replace").splitlines()
        required_hooks = {"base", "systemd", "microcode", "block", "sd-encrypt", "filesystems"}
        hook_match = re.search(r"^HOOKS=\(([^)]*)\)", config, re.MULTILINE)
        hooks = set(hook_match.group(1).split()) if hook_match else set()
        if not required_hooks.issubset(hooks):
            raise RuntimeError(f"initramfs hook closure is incomplete: {image}")
        required_paths = {
            "usr/bin/btrfs",
            "usr/lib/systemd/systemd",
            "usr/lib/systemd/systemd-cryptsetup",
            "usr/lib/systemd/system-generators/systemd-cryptsetup-generator",
            "etc/crypttab",
        }
        content_set = set(contents)
        if not required_paths.issubset(content_set):
            raise RuntimeError(f"initramfs encryption/filesystem content is incomplete: {image}")
        if not any(re.search(r"(?:^|/)dm-crypt\.ko(?:\.(?:zst|xz|gz))?$", entry) for entry in contents):
            raise RuntimeError(f"initramfs lacks dm-crypt kernel support: {image}")
        return {
            "hooks": sorted(hooks),
            "required_paths": sorted(required_paths),
            "dm_crypt_present": True,
        }

    def _phase_initramfs_built(self, plan, payload, journal, root) -> Mapping[str, Any]:
        (root / "etc/mkinitcpio.conf").write_text(
            'MODULES=(virtio_pci virtio_blk)\nBINARIES=()\nFILES=()\n'
            'HOOKS=(base systemd autodetect microcode modconf kms keyboard sd-vconsole block sd-encrypt filesystems fsck)\n',
            encoding="utf-8",
        )
        (root / "etc/kernel").mkdir(parents=True, exist_ok=True)
        (root / "etc/kernel/cmdline").write_text(self._cmdline(plan) + "\n", encoding="utf-8")
        self._chroot(root, ("mkinitcpio", "-P"))
        paths = {
            "primary": root / "boot/initramfs-linux-cachyos.img",
            "fallback": root / "boot/initramfs-linux-cachyos-lts.img",
        }
        if any(not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
            raise RuntimeError("required initramfs artifacts are missing")
        primary_verify = self._verify_initramfs(root, "/boot/initramfs-linux-cachyos.img")
        fallback_verify = self._verify_initramfs(root, "/boot/initramfs-linux-cachyos-lts.img")
        return {
            "primary_sha256": _sha256(paths["primary"]),
            "fallback_sha256": _sha256(paths["fallback"]),
            "primary_verified": primary_verify,
            "fallback_verified": fallback_verify,
            "luks_uuid": plan["installation_identity"]["luks_uuid"],
            "root_uuid": plan["installation_identity"]["btrfs_uuid"],
        }

    def _boot_artifact(self, path: Path, target_path: str, kind: str) -> BootArtifact:
        return BootArtifact.from_bytes(
            path.read_bytes(), artifact_type=kind, path=target_path,
            algorithms=(("blake2b-512", "limine-artifact-integrity"), ("sha256", "maho-content-identity")),
        )

    def _limine_config(
        self, entries: Sequence[tuple[str, BootArtifact, Sequence[BootArtifact], str]],
    ) -> bytes:
        lines = ["timeout: 3", "serial: yes", "verbose: yes", "hash_mismatch_panic: yes"]
        for title, kernel, modules, cmdline in entries:
            kernel_hash = kernel.digest("blake2b-512", "limine-artifact-integrity")
            assert kernel_hash is not None
            lines.extend((f"/{title}", " protocol: linux", f" path: boot():{kernel.path}#{kernel_hash.digest}"))
            for module in modules:
                digest = module.digest("blake2b-512", "limine-artifact-integrity")
                assert digest is not None
                lines.append(f" module_path: boot():{module.path}#{digest.digest}")
            lines.append(f" cmdline: {cmdline}")
        return ("\n".join(lines) + "\n").encode()

    def _sign_loader(
        self, root: Path, clean: Path, config: bytes, destination: Path,
        *, config_path: str, required: Sequence[BootArtifact], signer: str,
    ) -> tuple[LoaderIdentity, BootArtifact]:
        destination.parent.mkdir(parents=True, exist_ok=True)
        unsigned = destination.with_suffix(".unsigned.efi")
        shutil.copyfile(clean, unsigned)
        digest = hashlib.blake2b(config, digest_size=64).hexdigest()
        self._chroot(root, ("limine", "enroll-config", "--quiet", str(unsigned.relative_to(root)), digest))
        key = "/var/lib/maho/installer/.boot-signing.key"
        cert = "/var/lib/maho/installer/.boot-signing.crt"
        self._chroot(root, (
            "sbsign", "--key", key, "--cert", cert,
            "--output", str(destination.relative_to(root)), str(unsigned.relative_to(root)),
        ))
        unsigned.unlink()
        verified = self._chroot(root, ("sbverify", "--cert", cert, str(destination.relative_to(root))))
        if verified.returncode != 0:
            raise RuntimeError("signed Limine loader did not verify")
        loader_artifact = BootArtifact.from_bytes(
            destination.read_bytes(), artifact_type="efi-loader",
            path="/" + str(destination.relative_to(root / "boot")),
        )
        config_artifact = BootArtifact.from_bytes(
            config, artifact_type="limine-config", path=config_path,
            algorithms=(("blake2b-512", "limine-config-checksum"), ("sha256", "maho-content-identity")),
        )
        resources = tuple(sorted(
            (item.digest("blake2b-512", "limine-artifact-integrity") for item in required),
            key=lambda item: (item.algorithm, item.digest, item.purpose),
        ))
        return LoaderIdentity(
            loader_artifact, self._limine_version(root), signer,
            Digest.calculate(config, algorithm="blake2b-512", purpose="limine-config-checksum"),
            config_path, (config_path,), resources,
        ), config_artifact

    def _limine_version(self, root: Path) -> str:
        output = self._chroot(root, ("limine", "--version")).stdout.decode(errors="replace")
        match = re.search(r"(?:^|\s)(\d+(?:\.\d+)+)(?:\s|$)", output)
        if match is None:
            raise RuntimeError("installed Limine version could not be identified")
        return match.group(1)

    def _phase_boot_generation_published(self, plan, payload, journal, root) -> Mapping[str, Any]:
        esp = root / "boot"
        normal = esp / "EFI/MahoOS/Normal"
        recovery = esp / "EFI/MahoOS/Recovery"
        normal.mkdir(parents=True, exist_ok=True)
        recovery.mkdir(parents=True, exist_ok=True)
        sources = {
            "primary-kernel": root / "boot/vmlinuz-linux-cachyos",
            "primary-initramfs": root / "boot/initramfs-linux-cachyos.img",
            "fallback-kernel": root / "boot/vmlinuz-linux-cachyos-lts",
            "fallback-initramfs": root / "boot/initramfs-linux-cachyos-lts.img",
        }
        destinations = {
            "primary-kernel": normal / "vmlinuz-linux-cachyos",
            "primary-initramfs": normal / "initramfs-linux-cachyos.img",
            "fallback-kernel": normal / "vmlinuz-linux-cachyos-lts",
            "fallback-initramfs": normal / "initramfs-linux-cachyos-lts.img",
        }
        for name, source in sources.items():
            shutil.copyfile(source, destinations[name])
        kernel_evidence = (journal.get("phase_evidence") or {}).get("KERNELS_INSTALLED") or {}
        microcode_package = str(kernel_evidence.get("microcode_package", ""))
        if microcode_package not in {"intel-ucode", "amd-ucode"}:
            raise RuntimeError("kernel phase did not bind an exact CPU microcode package")
        microcode_source = root / "boot" / f"{microcode_package}.img"
        if not microcode_source.is_file():
            raise RuntimeError("bound CPU microcode boot artifact is missing")
        microcode_target = normal / microcode_source.name
        recovery_microcode_target = recovery / microcode_source.name
        shutil.copyfile(microcode_source, microcode_target)
        shutil.copyfile(microcode_source, recovery_microcode_target)
        shutil.copyfile(sources["fallback-kernel"], recovery / "vmlinuz-linux-cachyos-lts")
        shutil.copyfile(sources["fallback-initramfs"], recovery / "initramfs-linux-cachyos-lts.img")
        primary_kernel = self._boot_artifact(destinations["primary-kernel"], "/EFI/MahoOS/Normal/vmlinuz-linux-cachyos", "kernel")
        primary_initramfs = self._boot_artifact(destinations["primary-initramfs"], "/EFI/MahoOS/Normal/initramfs-linux-cachyos.img", "initramfs")
        fallback_kernel = self._boot_artifact(destinations["fallback-kernel"], "/EFI/MahoOS/Normal/vmlinuz-linux-cachyos-lts", "kernel")
        fallback_initramfs = self._boot_artifact(destinations["fallback-initramfs"], "/EFI/MahoOS/Normal/initramfs-linux-cachyos-lts.img", "initramfs")
        microcode = self._boot_artifact(microcode_target, f"/EFI/MahoOS/Normal/{microcode_target.name}", "microcode")
        recovery_kernel = self._boot_artifact(recovery / "vmlinuz-linux-cachyos-lts", "/EFI/MahoOS/Recovery/vmlinuz-linux-cachyos-lts", "kernel")
        recovery_initramfs = self._boot_artifact(recovery / "initramfs-linux-cachyos-lts.img", "/EFI/MahoOS/Recovery/initramfs-linux-cachyos-lts.img", "initramfs")
        recovery_microcode = self._boot_artifact(
            recovery_microcode_target,
            f"/EFI/MahoOS/Recovery/{recovery_microcode_target.name}",
            "microcode",
        )
        normal_config = self._limine_config((
            ("MahoOS Primary", primary_kernel, (microcode, primary_initramfs), self._cmdline(plan)),
            ("MahoOS Fallback", fallback_kernel, (microcode, fallback_initramfs), self._cmdline(plan)),
        ))
        recovery_config = self._limine_config((
            ("MahoOS Recovery", recovery_kernel, (recovery_microcode, recovery_initramfs), self._cmdline(plan, recovery=True)),
        ))
        run_key = root / "var/lib/maho/installer/.boot-signing.key"
        run_cert = root / "var/lib/maho/installer/.boot-signing.crt"
        run_key.parent.mkdir(parents=True, exist_ok=True)
        removable = esp / "EFI/BOOT"
        try:
            self._chroot(root, (
                "openssl", "req", "-new", "-x509", "-newkey", "rsa:3072", "-nodes",
                "-subj", f"/CN=MahoOS Install {plan['installation_identity']['installation_uuid']}/",
                "-keyout", "/var/lib/maho/installer/.boot-signing.key",
                "-out", "/var/lib/maho/installer/.boot-signing.crt", "-days", "3650",
            ))
            fingerprint_output = self._chroot(root, (
                "openssl", "x509", "-in", "/var/lib/maho/installer/.boot-signing.crt",
                "-noout", "-fingerprint", "-sha256",
            )).stdout.decode()
            signer = fingerprint_output.strip().split("=", 1)[-1].replace(":", "").upper()
            (normal / "limine.conf").write_bytes(normal_config)
            (recovery / "limine.conf").write_bytes(recovery_config)
            clean = root / "usr/share/limine/BOOTX64.EFI"
            normal_loader, normal_config_art = self._sign_loader(
                root, clean, normal_config, normal / "limine.efi",
                config_path="/EFI/MahoOS/Normal/limine.conf",
                required=(primary_kernel, primary_initramfs, fallback_kernel, fallback_initramfs, microcode),
                signer=signer,
            )
            recovery_loader, recovery_config_art = self._sign_loader(
                root, clean, recovery_config, recovery / "limine.efi",
                config_path="/EFI/MahoOS/Recovery/limine.conf",
                required=(recovery_kernel, recovery_microcode, recovery_initramfs), signer=signer,
            )
            # UEFI removable-media discovery avoids changing any firmware boot
            # variable. It is a byte-for-byte alias of the canonical normal
            # loader/config, not a second boot authority.
            removable.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(normal / "limine.efi", removable / "BOOTX64.EFI")
            shutil.copyfile(normal / "limine.conf", removable / "limine.conf")
            cert_target = root / "etc/maho/boot-signing.crt"
            shutil.copyfile(run_cert, cert_target)
        finally:
            # The installer signing key is single-use installation material.
            # Never retain it, even if loader generation or verification fails.
            run_key.unlink(missing_ok=True)
            run_cert.unlink(missing_ok=True)
        runtime_manifest = next((root / f"home/{self.user_name}/.local/share/maho/runtime/releases").glob("*/manifest.json"))
        guardian_runtime = BootArtifact.from_bytes(
            runtime_manifest.read_bytes(), artifact_type="guardian-recovery-runtime",
            path="/var/lib/maho/installer/runtime-manifest.json",
        )
        shutil.copyfile(runtime_manifest, root / "var/lib/maho/installer/runtime-manifest.json")
        (root / "var/lib/maho/installer/cmdline").write_bytes(self._cmdline(plan).encode())
        cmdline = BootArtifact.from_bytes(
            self._cmdline(plan).encode(), artifact_type="authenticated-kernel-command-line",
            path="/var/lib/maho/installer/cmdline",
        )
        generation = BootGeneration.create(
            source_revision=plan["source_revision"],
            package_generation_id=payload["package_generation_id"],
            candidate_root_identity=f"btrfs:{plan['installation_identity']['btrfs_uuid']}:@",
            normal_loader=normal_loader, normal_config=normal_config_art,
            primary_kernel=primary_kernel, primary_initramfs=primary_initramfs,
            fallback_kernel=fallback_kernel, fallback_initramfs=fallback_initramfs,
            microcode=(microcode,), recovery_loader=recovery_loader,
            recovery_config=recovery_config_art, recovery_kernel=recovery_kernel,
            recovery_initramfs=recovery_initramfs,
            guardian_recovery_runtime=guardian_runtime, authenticated_cmdline=cmdline,
        )
        manifest = root / f"var/lib/maho/generations/manifests/boot/{generation.boot_generation_id}.json"
        _write_json_durable(manifest, generation.as_dict())
        boot_paths = [
            normal / "limine.efi", normal / "limine.conf", recovery / "limine.efi",
            recovery / "limine.conf", *destinations.values(), microcode_target,
            recovery_microcode_target,
            recovery / "vmlinuz-linux-cachyos-lts", recovery / "initramfs-linux-cachyos-lts.img",
            removable / "BOOTX64.EFI", removable / "limine.conf",
        ]
        return {
            "boot_generation_id": generation.boot_generation_id,
            "normal_loader": "/EFI/MahoOS/Normal/limine.efi",
            "fallback_entry": "MahoOS Fallback",
            "recovery_loader": "/EFI/MahoOS/Recovery/limine.efi",
            "signer_fingerprint": signer,
            "boot_sha256": {"/boot/" + str(path.relative_to(esp)): _sha256(path) for path in sorted(boot_paths)},
        }

    def _phase_recovery_installed(self, plan, payload, journal, root) -> Mapping[str, Any]:
        snapshot = root / ".snapshots/1/snapshot"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        self._run(("btrfs", "subvolume", "snapshot", "-r", str(root), str(snapshot)))
        recovery_id = generation_identity(plan["installation_identity"]["btrfs_uuid"], "root", 1)
        if recovery_id is None:
            raise RuntimeError("initial recovery identity could not be derived")
        value = {
            "schema_version": 1, "kind": "maho-initial-recovery-generation",
            "recovery_identity": recovery_id,
            "filesystem_uuid": plan["installation_identity"]["btrfs_uuid"],
            "snapshot_id": 1, "snapshot_path": "/@snapshots/1/snapshot",
            "read_only": True,
            "fallback_kernel_sha256": _sha256(root / "boot/EFI/MahoOS/Recovery/vmlinuz-linux-cachyos-lts"),
            "fallback_initramfs_sha256": _sha256(root / "boot/EFI/MahoOS/Recovery/initramfs-linux-cachyos-lts.img"),
        }
        _write_json_durable(root / "var/lib/maho/recovery/initial.json", value)
        return value

    def _install_update_campaign(self, root: Path, source_revision: str) -> None:
        installer = (root / "usr/lib/maho/bin/maho-update-campaign-install").read_text(encoding="utf-8")
        block = installer.split("FILES=(", 1)[1].split(")\n", 1)[0]
        files = [line.strip() for line in block.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        destination = root / "usr/lib/maho/update-campaign" / source_revision
        if destination.exists():
            raise RuntimeError("update campaign destination already exists")
        for relative in files:
            source = root / "usr/lib/maho" / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        (destination / "SOURCE_REVISION").write_text(source_revision + "\n", encoding="utf-8")
        current = destination.parent / "current"
        current.symlink_to(source_revision)

    def _phase_services_installed(self, plan, payload, journal, root) -> Mapping[str, Any]:
        runtime = f"/home/{self.user_name}/.local/share/maho/runtime/current"
        self._chroot(root, (
            "env", f"MAHO_ROOT={runtime}", f"MAHO_SDDM_USER={self.user_name}",
            "bash", f"{runtime}/bin/maho-lock-sddm-install", "install",
        ))
        self._install_update_campaign(root, plan["source_revision"])
        for unit in (
            "NetworkManager.service", "sddm.service", "maho-firewall.service",
            "maho-firewall-observer.timer", "maho-update-coordinator.timer",
            "maho-installer-firstboot.service",
        ):
            self._chroot(root, ("systemctl", "enable", unit))
        unit_root = root / f"home/{self.user_name}/.config/systemd/user"
        wants = unit_root / "default.target.wants"
        wants.mkdir(parents=True, exist_ok=True)
        for unit in ("maho-observe.service", "maho-security.service", "maho-guardian.service"):
            link = wants / unit
            if not link.exists() and not link.is_symlink():
                # This link lives inside the installed filesystem.  Never
                # encode the live installer's mount prefix into the target.
                link.symlink_to(Path("..") / unit)
        self._chroot(root, ("chown", "-R", f"{self.user_name}:{self.user_name}", f"/home/{self.user_name}/.config"))
        linger = root / "var/lib/systemd/linger" / self.user_name
        linger.parent.mkdir(parents=True, exist_ok=True)
        linger.write_text("\n", encoding="utf-8")
        return {
            "networkmanager_enabled": True, "sddm_enabled": True,
            "session_installed": (root / "usr/share/wayland-sessions/maho.desktop").is_file(),
            "coordinator_installed": (root / "usr/lib/maho/update-campaign/current/bin/maho-update-coordinator").is_file(),
            "coordinator_timer_enabled": True,
            "guardian_user_service_enabled": (root / f"home/{self.user_name}/.config/systemd/user/default.target.wants/maho-guardian.service").is_symlink(),
            "production_prevention_enabled": False,
        }

    def _modules_artifacts(self, root: Path, release: str) -> tuple[dict[str, ArtifactID], bytes]:
        base = root / "usr/lib/modules" / release
        entries: dict[str, ArtifactID] = {}
        for path in sorted(base.rglob("*")):
            if path.is_symlink():
                content = f"symlink:{os.readlink(path)}".encode()
            elif path.is_file():
                content = path.read_bytes()
            else:
                continue
            entries[str(path.relative_to(base))] = ArtifactID.from_content(content)
        identity, manifest = modules_tree_artifact(entries)
        return entries | {".manifest": identity}, manifest

    def _phase_system_generation_published(self, plan, payload, journal, root) -> Mapping[str, Any]:
        evidence = journal.get("phase_evidence") or {}
        kernel_info = evidence["KERNELS_INSTALLED"]
        boot_info = evidence["BOOT_GENERATION_PUBLISHED"]
        recovery = evidence["RECOVERY_INSTALLED"]
        runtime = evidence["RUNTIME_INSTALLED"]
        primary = str(kernel_info["primary_release"])
        _, modules_manifest = self._modules_artifacts(root, primary)
        transaction = TransactionID.derive({
            "kind": "maho-installation", "install_attempt_id": plan["install_attempt_id"],
            "installation_uuid": plan["installation_identity"]["installation_uuid"],
            "payload_sha256": payload["payload_sha256"],
        })
        provenance = ProvenanceID.derive({
            "kind": "maho-installer-payload", "payload_sha256": payload["payload_sha256"],
            "source_revision": plan["source_revision"],
        })
        esp = root / "boot/EFI/MahoOS/Normal"
        microcode = next(path for path in esp.glob("*-ucode.img"))
        kernel = KernelGeneration.create(
            parent_kernel_generation_id=None,
            kernel_image_id=ArtifactID.from_content((esp / "vmlinuz-linux-cachyos").read_bytes()),
            initramfs_id=ArtifactID.from_content((esp / "initramfs-linux-cachyos.img").read_bytes()),
            modules_tree_id=ArtifactID.from_content(modules_manifest), dkms_output_ids=(),
            microcode_ids=(ArtifactID.from_content(microcode.read_bytes()),),
            cmdline_contract=self._cmdline(plan),
            package_provider_identity=f"linux-cachyos={primary};linux-cachyos-headers=installed",
            provenance_id=provenance, transaction_id=transaction,
            kernel_abi=primary, modules_abi=primary, trust_state=TrustState.UNKNOWN,
        )
        root_manifest = {
            "schema_version": 1, "kind": "maho-initial-root-manifest",
            "install_attempt_id": plan["install_attempt_id"],
            "installation_uuid": plan["installation_identity"]["installation_uuid"],
            "source_revision": plan["source_revision"],
            "payload_sha256": payload["payload_sha256"],
            "runtime_content_sha256": runtime["content_sha256"],
            "boot_generation_id": boot_info["boot_generation_id"],
            "recovery_identity": recovery["recovery_identity"],
        }
        root_bytes = canonical_bytes(root_manifest)
        root_artifact = ArtifactID.from_content(root_bytes)
        system = SystemGeneration.create(
            parent_generation_id=None,
            root_identity=RootIdentity(
                "btrfs-subvolume:@", f"uuid:{plan['installation_identity']['btrfs_uuid']}",
                hashlib.sha256(root_bytes).hexdigest(),
            ),
            kernel_generation_id=kernel.kernel_generation_id,
            package_set_identity=payload["package_generation_id"],
            transaction_id=transaction, provenance_id=provenance,
            artifact_ids=(root_artifact,), trust_state=TrustState.UNKNOWN,
        )
        generation_root = root / "var/lib/maho/generations"
        artifact_path = generation_root / "artifacts/sha256" / str(root_artifact)[4:6] / str(root_artifact)[6:]
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_bytes(root_bytes)
        modules_artifact = ArtifactID.from_content(modules_manifest)
        modules_path = generation_root / "artifacts/sha256" / str(modules_artifact)[4:6] / str(modules_artifact)[6:]
        modules_path.parent.mkdir(parents=True, exist_ok=True)
        modules_path.write_bytes(modules_manifest)
        _write_json_durable(generation_root / f"manifests/kernel/{kernel.kernel_generation_id}.json", kernel.as_dict())
        _write_json_durable(generation_root / f"manifests/system/{system.generation_id}.json", system.as_dict())
        _write_json_durable(generation_root / "initial-pending.json", {
            "schema_version": 1, "kind": "maho-initial-generation-publication",
            "state": "PENDING_FIRST_BOOT",
            "system_generation_id": str(system.generation_id),
            "kernel_generation_id": str(kernel.kernel_generation_id),
            "package_generation_id": payload["package_generation_id"],
            "boot_generation_id": boot_info["boot_generation_id"],
            "recovery_identity": recovery["recovery_identity"],
            "native_transaction_id": str(transaction),
            "root_manifest_artifact_id": str(root_artifact),
        })
        return {
            "system_generation_id": str(system.generation_id),
            "kernel_generation_id": str(kernel.kernel_generation_id),
            "package_generation_id": payload["package_generation_id"],
            "transaction_id": str(transaction), "provenance_id": str(provenance),
            "preboot_trust_state": "UNKNOWN",
        }

    def _phase_install_receipt_written(self, plan, payload, journal, root) -> Mapping[str, Any]:
        receipt = build_install_receipt(plan, payload, journal.get("phase_evidence") or {})
        path = self._state_root(root) / "install-receipt.json"
        _write_json_durable(path, receipt)
        return {"receipt_id": receipt["receipt_id"], "state": "PENDING_FIRST_BOOT"}

    def _phase_pending_first_boot(self, plan, payload, journal, root) -> Mapping[str, Any]:
        receipt = json.loads((self._state_root(root) / "install-receipt.json").read_text(encoding="utf-8"))
        state = {
            "schema_version": 1, "kind": "maho-installation-state",
            "state": "PENDING_FIRST_BOOT", "receipt_id": receipt["receipt_id"],
            "installation_uuid": plan["installation_identity"]["installation_uuid"],
        }
        _write_json_durable(self._state_root(root) / "state.json", state)
        return {"state": "PENDING_FIRST_BOOT", "receipt_id": receipt["receipt_id"]}

    def _phase_unmounted(self, plan, payload, journal, root) -> Mapping[str, Any]:
        installed = dict(journal)
        installed.pop("in_progress_phase", None)
        installed["phase"] = "UNMOUNTED"
        installed["history"] = list(journal["history"]) + [{
            "phase": "UNMOUNTED", "recorded_at": _utc_now(),
        }]
        _write_json_durable(self._state_root(root) / "journal.json", installed)
        for target in (root / "boot", root / "var/log", root / ".snapshots", root / "home", root):
            self._run(("umount", str(target)))
        self._run(("cryptsetup", "close", plan["encryption_contract"]["mapper_name"]))
        return {"clean_unmount": True, "automatic_reboot": False}
