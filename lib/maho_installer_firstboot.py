#!/usr/bin/env python3
"""Observation-only certification of the first boot of an installed MahoOS."""
from __future__ import annotations

from datetime import datetime, timezone
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
from typing import Any, Callable, Mapping, Protocol, Sequence

from guardian_evidence import ProviderHealth, parse_timestamp
from guardian_live_state import GUARDIAN_SPECS, SECURITY_SPECS
from guardian_provider_state import load_heartbeat
from maho_firewall_receipt import verify as verify_firewall_receipt
from maho_installer_execute import _checkpoint, _mutation_lock, _read_journal, _write_json_durable
from maho_installer_receipt import certify_first_boot, validate_install_receipt
from maho_live_generation import publish_initial_live_generations, read_live_publication
from maho_runtime_release import verify_release
from maho_update_discovery import parse_name_versions


INSTALLER_ROOT = Path("/var/lib/maho/installer")
GENERATION_ROOT = Path("/var/lib/maho/generations")


class FirstBootObserver(Protocol):
    def observe(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class SystemFirstBootObserver:
    """Collect live evidence without changing installation state."""

    def _run(self, command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            list(command), text=True, capture_output=True, check=False,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"first-boot observation failed ({command[0]}): {detail}")
        return result

    def _mount(self, target: str) -> Mapping[str, Any]:
        result = self._run(("findmnt", "--json", "--target", target, "--output", "SOURCE,FSTYPE,FSROOT,UUID"))
        value = json.loads(result.stdout)
        rows = value.get("filesystems") if isinstance(value, Mapping) else None
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], Mapping):
            raise RuntimeError(f"mount observation is ambiguous: {target}")
        return rows[0]

    def _shadow_password_field(self, account: str) -> str:
        result = self._run(("getent", "shadow", account))
        fields = result.stdout.rstrip("\n").split(":")
        if len(fields) < 2 or fields[0] != account or not fields[1]:
            raise RuntimeError(f"shadow account observation is unavailable: {account}")
        return fields[1]

    def _luks_uuid(self, device: str) -> str:
        if not device.startswith("/dev/"):
            raise RuntimeError("active LUKS backing device identity is invalid")
        result = self._run(("blkid", "-s", "UUID", "-o", "value", device))
        value = result.stdout.strip()
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", value):
            raise RuntimeError("active LUKS UUID observation is unavailable")
        return value.lower()

    def _subvolume_uuid(self, target: str) -> str:
        result = self._run(("btrfs", "subvolume", "show", target))
        value = next(
            (line.split(":", 1)[1].strip() for line in result.stdout.splitlines()
             if line.strip().startswith("UUID:")),
            "",
        )
        if not value:
            raise RuntimeError(f"Btrfs subvolume UUID is unavailable: {target}")
        return value

    def _package_versions(self) -> dict[str, str]:
        lock = Path("/var/lib/pacman/db.lck")
        if lock.exists():
            raise RuntimeError("package operation is active during first-boot observation")
        packages = parse_name_versions(self._run(("pacman", "-Q")).stdout, separator=" ")
        if not packages or lock.exists():
            raise RuntimeError("installed package inventory is unavailable or changing")
        return packages

    def _guardian(self, user_name: str, boot_id: str) -> dict[str, Any]:
        result = self._run((
            "runuser", "-u", user_name, "--", "env", "XDG_RUNTIME_DIR=/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus",
            "systemctl", "--user", "is-active", "maho-guardian.service",
        ), check=False)
        state_root = Path(f"/home/{user_name}/.local/state/maho/security")
        now = datetime.now(timezone.utc)
        fresh = True
        observed: dict[str, str] = {}
        for spec in (*SECURITY_SPECS, *GUARDIAN_SPECS):
            if not spec.required:
                continue
            heartbeat = load_heartbeat(state_root, spec.provider_id)
            if heartbeat is None or heartbeat.last_success_at is None:
                fresh = False
                continue
            stamp = parse_timestamp(heartbeat.last_success_at)
            current = (now - stamp).total_seconds() <= spec.max_age_seconds
            same_boot = heartbeat.boot_id in {None, boot_id}
            usable = current and same_boot and heartbeat.health is not ProviderHealth.FAILED
            fresh = fresh and usable
            observed[spec.provider_id] = heartbeat.health.value
        return {
            "service_active": result.returncode == 0 and result.stdout.strip() == "active",
            "required_evidence_fresh": fresh,
            "provider_health": observed,
            # Installation health does not manufacture boot or generation trust.
            "trust_state": "UNKNOWN",
        }

    def observe(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]:
        expected = validate_install_receipt(receipt)
        packages = self._package_versions()
        identity = json.loads(Path("/etc/maho/installation.json").read_text(encoding="utf-8"))
        root_mount = self._mount("/")
        home_mount = self._mount(f"/home/{expected['user']['name']}")
        mapper = expected["storage"]["mapper_name"]
        crypt = self._run(("cryptsetup", "status", mapper))
        device = next(
            (line.split(":", 1)[1].strip() for line in crypt.stdout.splitlines()
             if line.strip().startswith("device:")),
            "",
        )
        luks_uuid = self._luks_uuid(device) if device else ""
        pending = json.loads((GENERATION_ROOT / "initial-pending.json").read_text(encoding="utf-8"))
        user_name = expected["user"]["name"]
        runtime_root = Path(f"/home/{user_name}/.local/share/maho/runtime")
        runtime = verify_release(runtime_root / "current", runtime_root / "releases")
        boot_hashes = {
            path: _sha256(Path(path)) for path in sorted(expected["boot"]["boot_sha256"])
        }
        recovery = json.loads(Path("/var/lib/maho/recovery/initial.json").read_text(encoding="utf-8"))
        account = pwd.getpwnam(user_name)
        groups = {item.gr_name for item in grp.getgrall() if user_name in item.gr_mem}
        groups.add(grp.getgrgid(account.pw_gid).gr_name)
        root_shadow = self._shadow_password_field("root")
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
        firewall = verify_firewall_receipt(expected_boot_id=boot_id)
        failed = [
            line.split()[0] for line in self._run(
                ("systemctl", "--failed", "--plain", "--no-legend", "--no-pager"), check=False,
            ).stdout.splitlines() if line.strip()
        ]
        enabled = lambda unit: self._run(("systemctl", "is-enabled", unit), check=False).returncode == 0
        active = lambda unit: self._run(("systemctl", "is-active", unit), check=False).returncode == 0
        observation = {
            "storage": {
                "btrfs_uuid": str(root_mount.get("uuid", "")),
                "root_fsroot": str(root_mount.get("fsroot", "")),
                "root_subvolume_uuid": self._subvolume_uuid("/"),
                "home_subvolume_uuid": self._subvolume_uuid("/home"),
                "luks_uuid": luks_uuid,
                "mapper_name": mapper if str(root_mount.get("source", "")).split("[", 1)[0].endswith(mapper) else "",
                "installation_uuid": identity.get("installation_uuid"),
            },
            "machine_id": Path("/etc/machine-id").read_text(encoding="utf-8").strip(),
            "generations": {
                key: pending.get(key) for key in (
                    "system_generation_id", "package_generation_id",
                    "kernel_generation_id", "boot_generation_id",
                )
            },
            "package_versions": packages,
            "runtime": {
                "source_revision": runtime.source_revision,
                "content_sha256": runtime.content_sha256,
                "deployment_class": runtime.deployment_class,
                "trust_eligible": runtime.trust_eligible,
                "verified": runtime.verified,
            },
            "boot": {
                "running_kernel": os.uname().release,
                "cmdline": Path("/proc/cmdline").read_text(encoding="utf-8").strip(),
                "boot_sha256": boot_hashes,
                "fallback_artifacts_present": all(
                    Path(path).is_file() for path in expected["boot"]["boot_sha256"]
                    if "cachyos-lts" in path or "/Recovery/" in path
                ),
            },
            "guardian": self._guardian(user_name, boot_id),
            "recovery": {
                "recovery_identity": recovery.get("recovery_identity"),
                "artifacts_present": all((
                    Path("/.snapshots/1/snapshot").is_dir(),
                    Path("/boot/EFI/MahoOS/Recovery/limine.efi").is_file(),
                    Path("/boot/EFI/MahoOS/Recovery/limine.conf").is_file(),
                )),
            },
            "user": {
                "name": account.pw_name, "uid": account.pw_uid,
                "wheel": "wheel" in groups,
                "root_locked": root_shadow.startswith(("!", "*")),
                "home_fsroot": str(home_mount.get("fsroot", "")),
            },
            "services": {
                "networkmanager_enabled": enabled("NetworkManager.service"),
                "networkmanager_active": active("NetworkManager.service"),
                "sddm_enabled": enabled("sddm.service"),
                "session_installed": Path("/usr/share/wayland-sessions/maho.desktop").is_file(),
                "coordinator_installed": Path("/usr/lib/maho/update-campaign/current/bin/maho-update-coordinator").is_file(),
                "coordinator_timer_enabled": enabled("maho-update-coordinator.timer"),
                "firewall_enabled": enabled("maho-firewall.service"),
                "guardian_user_service_enabled": Path(f"/home/{user_name}/.config/systemd/user/default.target.wants/maho-guardian.service").is_symlink(),
                "production_prevention_enabled": enabled("maho-prevention-boundary.service"),
            },
            "firewall": firewall,
            "failed_units": failed,
            "boot_id": boot_id,
        }
        if self._package_versions() != packages:
            raise RuntimeError("installed package inventory changed during first-boot observation")
        return observation


def run_first_boot(
    *, installer_root: Path = INSTALLER_ROOT, generation_root: Path = GENERATION_ROOT,
    observer: FirstBootObserver | None = None,
    publisher: Callable[..., Mapping[str, Any]] = publish_initial_live_generations,
    require_root: bool = True,
) -> dict[str, Any]:
    """Observe, certify, and durably publish health for one install attempt."""
    if require_root and os.geteuid() != 0:
        raise PermissionError("first-boot certification requires root")
    journal_path = installer_root / "journal.json"
    receipt_path = installer_root / "install-receipt.json"
    with _mutation_lock(journal_path):
        journal = _read_journal(journal_path)
        if journal["phase"] == "INSTALLATION_HEALTHY":
            return json.loads((installer_root / "first-boot-result.json").read_text(encoding="utf-8"))
        if journal["phase"] == "UNMOUNTED":
            journal = _checkpoint(journal_path, journal, "FIRST_BOOT_VERIFYING")
        elif journal["phase"] != "FIRST_BOOT_VERIFYING":
            raise RuntimeError("installer journal is not pending first-boot verification")
        receipt = validate_install_receipt(json.loads(receipt_path.read_text(encoding="utf-8")))
        try:
            observation = dict((observer or SystemFirstBootObserver()).observe(receipt))
            result = certify_first_boot(receipt, observation)
            if result["state"] == "INSTALLATION_HEALTHY":
                publication = dict(publisher(receipt, observation, root=generation_root))
                if publication.get("system_generation_id") != receipt["system_generation_id"]:
                    raise RuntimeError("initial live generation publication drifted")
                if read_live_publication(generation_root) is None:
                    raise RuntimeError("initial live generation publication is unreadable")
        except (OSError, ValueError, RuntimeError, KeyError, json.JSONDecodeError) as exc:
            result = {
                "schema_version": 1,
                "kind": "maho-installation-first-boot-result",
                "state": "ATTENTION_REQUIRED",
                "installation_receipt_id": receipt["receipt_id"],
                "blockers": [f"first_boot_observation_failed:{type(exc).__name__}:{exc}"],
                "healthy_receipt": None,
            }
        _write_json_durable(installer_root / "first-boot-result.json", result)
        if result["state"] != "INSTALLATION_HEALTHY":
            _write_json_durable(installer_root / "state.json", {
                "schema_version": 1, "kind": "maho-installation-state",
                "state": "ATTENTION_REQUIRED", "receipt_id": receipt["receipt_id"],
                "installation_uuid": receipt["installation_uuid"],
                "blockers": result["blockers"],
            })
            return result
        health = result["healthy_receipt"]
        _write_json_durable(installer_root / "installation-healthy.json", health)
        _write_json_durable(installer_root / "state.json", {
            "schema_version": 1, "kind": "maho-installation-state",
            "state": "INSTALLATION_HEALTHY", "receipt_id": receipt["receipt_id"],
            "installation_uuid": receipt["installation_uuid"],
            "health_receipt_id": health["health_receipt_id"],
        })
        _checkpoint(journal_path, journal, "INSTALLATION_HEALTHY", evidence={
            "health_receipt_id": health["health_receipt_id"], "boot_id": health["boot_id"],
        })
        return result
