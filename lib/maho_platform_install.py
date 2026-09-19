#!/usr/bin/env python3
"""Transactional root platform policy installer for MahoOS.

The platform transaction owns only Maho-marked policy files and the bounded
provider activation needed by those files.  It never restarts the graphical
session, portals, or keyring.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

MARKER = "# managed-by: maho-platform v1"
KEEP_TRANSACTIONS = 12

class PlatformError(RuntimeError):
    pass


def env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default))


class PlatformInstaller:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.source = root / "config/platform"
        self.portal_root = env_path("MAHO_PLATFORM_PORTAL_ROOT", "/etc/xdg/xdg-desktop-portal")
        self.timesync_root = env_path("MAHO_PLATFORM_TIMESYNC_ROOT", "/etc/systemd/timesyncd.conf.d")
        self.dbus_root = env_path("MAHO_PLATFORM_DBUS_ROOT", "/usr/local/share/dbus-1/services")
        self.zram_root = env_path("MAHO_PLATFORM_ZRAM_ROOT", "/etc/systemd/zram-generator.conf.d")
        self.systemd_root = env_path("MAHO_PLATFORM_SYSTEMD_ROOT", "/etc/systemd/system")
        self.user_systemd_root = env_path("MAHO_PLATFORM_USER_SYSTEMD_ROOT", "/etc/systemd/user")
        self.state_root = env_path("MAHO_PLATFORM_STATE_ROOT", "/var/lib/maho-platform")
        self.lock_file = env_path("MAHO_PLATFORM_LOCK_FILE", "/run/lock/maho-platform-install.lock")
        self.allow_unprivileged = os.environ.get("MAHO_PLATFORM_ALLOW_UNPRIVILEGED") == "1"
        self.system_unit_dirs = self._path_list("MAHO_PLATFORM_SYSTEM_UNIT_DIRS", "/etc/systemd/system:/run/systemd/system:/usr/local/lib/systemd/system:/usr/lib/systemd/system")
        self.user_unit_dirs = self._path_list("MAHO_PLATFORM_USER_UNIT_DIRS", "/etc/systemd/user:/run/systemd/user:/usr/local/lib/systemd/user:/usr/lib/systemd/user")
        self.portal_data_root = env_path("MAHO_PLATFORM_PORTAL_DATA_ROOT", "/usr/share/xdg-desktop-portal/portals")
        self.zram_generator = env_path("MAHO_PLATFORM_ZRAM_GENERATOR", "/usr/lib/systemd/system-generators/zram-generator")
        self.gnome_keyring = env_path("MAHO_PLATFORM_GNOME_KEYRING", "/usr/bin/gnome-keyring-daemon")
        self.btrfs = env_path("MAHO_PLATFORM_BTRFS", "/usr/bin/btrfs")
        self.files = self._file_map()
        self.providers = [
            "systemd-timesyncd.service",
            "systemd-oomd.service",
            "systemd-zram-setup@zram0.service",
            "rtkit-daemon.service",
            "maho-btrfs-scrub-root.timer",
        ]
        self.clock_conflicts = tuple(x for x in os.environ.get(
            "MAHO_PLATFORM_CLOCK_CONFLICT_UNITS",
            "chronyd.service ntpd.service ntp.service openntpd.service",
        ).split() if x)
        self.tx_dir: Path | None = None
        self.receipt: dict[str, object] = {}
        self.lock_handle = None

    @staticmethod
    def _path_list(name: str, default: str) -> list[Path]:
        return [Path(x) for x in os.environ.get(name, default).split(":") if x]

    def _file_map(self) -> list[tuple[str, Path, Path]]:
        return [
            ("portal", self.source / "maho-portals.conf", self.portal_root / "maho-portals.conf"),
            ("timesync", self.source / "systemd-timesyncd.conf", self.timesync_root / "60-maho.conf"),
            ("zram", self.source / "zram-generator.conf", self.zram_root / "60-maho.conf"),
            ("user-slice-oom", self.source / "user-.slice-memory-pressure.conf", self.systemd_root / "user-.slice.d/60-maho-memory-pressure.conf"),
            ("shell-oom", self.source / "maho-shell-memory-pressure.conf", self.user_systemd_root / "maho-shell.service.d/60-maho-memory-pressure.conf"),
            ("signed-boot-guard", self.source / "limine-snapper-sync-signed-boot.conf", self.systemd_root / "limine-snapper-sync.service.d/60-maho-signed-boot.conf"),
            ("scrub-service", self.source / "maho-btrfs-scrub-root.service", self.systemd_root / "maho-btrfs-scrub-root.service"),
            ("scrub-timer", self.source / "maho-btrfs-scrub-root.timer", self.systemd_root / "maho-btrfs-scrub-root.timer"),
            ("dbus-secrets", self.source / "org.freedesktop.secrets.service", self.dbus_root / "org.freedesktop.secrets.service"),
            ("dbus-keyring", self.source / "org.gnome.keyring.service", self.dbus_root / "org.gnome.keyring.service"),
            ("dbus-portal-secret", self.source / "org.freedesktop.impl.portal.Secret.service", self.dbus_root / "org.freedesktop.impl.portal.Secret.service"),
        ]

    def failpoint(self, point: str) -> None:
        if self.allow_unprivileged and os.environ.get("MAHO_PLATFORM_TEST_FAIL") == point:
            raise PlatformError(f"injected failure at {point}")

    def require_authority(self) -> None:
        if os.geteuid() == 0:
            return
        defaults = {
            self.portal_root: Path("/etc/xdg/xdg-desktop-portal"),
            self.timesync_root: Path("/etc/systemd/timesyncd.conf.d"),
            self.dbus_root: Path("/usr/local/share/dbus-1/services"),
            self.zram_root: Path("/etc/systemd/zram-generator.conf.d"),
            self.systemd_root: Path("/etc/systemd/system"),
            self.user_systemd_root: Path("/etc/systemd/user"),
            self.state_root: Path("/var/lib/maho-platform"),
        }
        if self.allow_unprivileged and all(actual != default for actual, default in defaults.items()):
            return
        raise PlatformError("system installation requires root")

    def _run(self, argv: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        except OSError as exc:
            result = subprocess.CompletedProcess(argv, 127, "", str(exc))
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip().splitlines()[-1]
            raise PlatformError(f"{' '.join(argv)}: {detail}")
        return result

    def _systemctl(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
        return self._run(["systemctl", *args], check=check)

    def _unit_file_exists(self, name: str, *, user: bool = False) -> bool:
        dirs = self.user_unit_dirs if user else self.system_unit_dirs
        return any((d / name).exists() for d in dirs)

    def _enabled_state(self, unit: str) -> str:
        result = self._systemctl("is-enabled", unit)
        value = (result.stdout or result.stderr).strip().splitlines()
        return value[-1].strip() if value else "unknown"

    def _active(self, unit: str) -> bool:
        return self._systemctl("is-active", "--quiet", unit).returncode == 0

    def _managed(self, path: Path) -> bool:
        try:
            return path.is_file() and MARKER in path.read_text(errors="replace").splitlines()
        except OSError:
            return False

    def _exact(self, source: Path, target: Path) -> bool:
        try:
            return self._managed(target) and source.read_bytes() == target.read_bytes()
        except OSError:
            return False

    def _nearest_existing_parent(self, path: Path) -> Path:
        parent = path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        return parent

    def _dir_writable(self, target: Path) -> bool:
        parent = self._nearest_existing_parent(target)
        return parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)

    def _dependency_checks(self) -> list[str]:
        errors: list[str] = []
        if shutil.which("systemctl") is None:
            errors.append("systemctl unavailable")
        for unit in ("systemd-timesyncd.service", "systemd-oomd.service", "rtkit-daemon.service"):
            if not self._unit_file_exists(unit):
                errors.append(f"required unit unavailable: {unit}")
        if not self._unit_file_exists("gnome-keyring-daemon.service", user=True):
            errors.append("required user unit unavailable: gnome-keyring-daemon.service")
        if not self.zram_generator.is_file() or not os.access(self.zram_generator, os.X_OK):
            errors.append("zram-generator unavailable")
        if not self.btrfs.is_file() or not os.access(self.btrfs, os.X_OK):
            errors.append("btrfs tooling unavailable")
        if not self.gnome_keyring.is_file() or not os.access(self.gnome_keyring, os.X_OK):
            errors.append("GNOME Keyring unavailable")
        for portal in ("gtk.portal", "hyprland.portal", "gnome-keyring.portal"):
            if not (self.portal_data_root / portal).is_file():
                errors.append(f"portal backend unavailable: {portal}")
        return errors

    def _masked(self, unit: str) -> bool:
        return self._enabled_state(unit).startswith("masked")

    def _configured_clock_units(self) -> tuple[str, ...]:
        units = set(self.clock_conflicts)
        result = self._systemctl("list-unit-files", "--type=service", "--no-legend", "--no-pager")
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = line.split()
                if not fields:
                    continue
                unit = fields[0]
                if unit != "systemd-timesyncd.service" and re.search(r"(?:ntp|chrony)", unit, re.IGNORECASE):
                    units.add(unit)
        return tuple(sorted(units))

    def _clock_conflicts(self) -> list[str]:
        found: list[str] = []
        for unit in self._configured_clock_units():
            active = self._active(unit)
            enabled = self._systemctl("is-enabled", "--quiet", unit).returncode == 0
            if active or enabled:
                found.append(f"{unit}({'active' if active else 'enabled'})")
        return found

    def preflight(self, *, check_lock: bool = True) -> list[str]:
        errors = self._dependency_checks()
        for _, source, target in self.files:
            if not source.is_file():
                errors.append(f"platform source missing: {source.name}")
                continue
            try:
                lines = source.read_text(errors="replace").splitlines()
            except OSError as exc:
                errors.append(f"platform source unreadable: {source.name}: {exc}")
                continue
            if MARKER not in lines:
                errors.append(f"platform source ownership marker missing: {source.name}")
            if target.is_symlink():
                errors.append(f"refusing symlink target: {target}")
            elif target.exists() and not self._managed(target):
                errors.append(f"refusing unmanaged target: {target}")
            if (os.geteuid() == 0 or self.allow_unprivileged) and not self._dir_writable(target):
                errors.append(f"destination not writable: {target.parent}")
        for unit in self.providers:
            if self._masked(unit):
                errors.append(f"required unit is masked: {unit}")
        conflicts = self._clock_conflicts()
        if conflicts:
            errors.append("conflicting clock authority: " + ", ".join(conflicts))
        if check_lock and self.lock_file.exists():
            try:
                with self.lock_file.open("a+") as handle:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        errors.append("another Maho platform transaction is in progress")
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                errors.append(f"platform transaction lock unavailable: {exc}")
        return errors

    def source_revision(self) -> str:
        provenance = self.root / "share/maho/runtime-source-revision"
        if provenance.is_file():
            value = provenance.read_text().strip()
            if re.fullmatch(r"[0-9a-f]{40}", value):
                return value
        release = self.root / "share/maho/release.json"
        if release.is_file():
            try:
                value = json.loads(release.read_text()).get("source_revision")
            except (OSError, json.JSONDecodeError):
                value = None
            if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value):
                return value
        result = self._run(["git", "-C", str(self.root), "rev-parse", "HEAD"])
        value = result.stdout.strip()
        return value if result.returncode == 0 and len(value) == 40 else "unknown"

    def state_identity(self) -> str:
        payload: dict[str, object] = {"files": {}, "services": {}}
        files = payload["files"]
        assert isinstance(files, dict)
        for name, _, target in self.files:
            if target.is_file():
                files[name] = {"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
            else:
                files[name] = {"path": str(target), "missing": True}
        services = payload["services"]
        assert isinstance(services, dict)
        for unit in self.providers:
            services[unit] = {"enabled": self._enabled_state(unit), "active": self._active(unit)}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def _capture_runtime_state(self) -> dict[str, object]:
        services = {unit: {"enabled": self._enabled_state(unit), "active": self._active(unit)} for unit in self.providers}
        zram: dict[str, object] = {"active": services["systemd-zram-setup@zram0.service"]["active"]}
        sys_zram = Path("/sys/block/zram0")
        for key in ("disksize", "comp_algorithm"):
            path = sys_zram / key
            try:
                zram[key] = path.read_text().strip()
            except OSError:
                zram[key] = None
        swapon = self._run(["swapon", "--show=NAME,TYPE,SIZE,USED,PRIO", "--noheadings"]) if shutil.which("swapon") else None
        zram["swap"] = swapon.stdout.strip() if swapon and swapon.returncode == 0 else None
        clock = {unit: {"enabled": self._enabled_state(unit), "active": self._active(unit)} for unit in ("systemd-timesyncd.service", *self.clock_conflicts)}
        return {"services": services, "zram": zram, "clock": clock}

    def _acquire_lock(self) -> None:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.lock_handle = self.lock_file.open("a+")
        try:
            os.chmod(self.lock_file, 0o600)
        except OSError:
            pass
        try:
            fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PlatformError("another Maho platform transaction is in progress") from exc

    def _new_transaction(self) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.state_root, 0o700)
        transactions = self.state_root / "transactions"
        transactions.mkdir(exist_ok=True)
        os.chmod(transactions, 0o700)
        txid = f"platform-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:10]}"
        self.tx_dir = transactions / txid
        self.tx_dir.mkdir(mode=0o700)
        (self.tx_dir / "backup").mkdir(mode=0o700)
        (self.tx_dir / "stage").mkdir(mode=0o700)
        self.receipt = {
            "schema_version": 1,
            "kind": "maho-platform-transaction",
            "transaction_id": txid,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source_revision": self.source_revision(),
            "status": "running",
            "files": [],
            "service_changes": [],
            "verification": {"ok": False, "errors": []},
            "rollback": {"attempted": False, "ok": None, "errors": []},
        }
        self.receipt["previous_state_identity"] = self.state_identity()
        self.receipt["previous_runtime_state"] = self._capture_runtime_state()
        self._write_receipt()

    def _write_receipt(self) -> None:
        if self.tx_dir is None:
            return
        path = self.tx_dir / "receipt.json"
        tmp = path.with_name(".receipt.tmp")
        data = (json.dumps(self.receipt, indent=2, sort_keys=True) + "\n").encode()
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(fd, data[offset:])
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)

    def _capture_backup(self) -> None:
        assert self.tx_dir is not None
        files_meta: list[dict[str, object]] = []
        for index, (name, source, target) in enumerate(self.files):
            item: dict[str, object] = {"name": name, "source": str(source), "target": str(target), "previous": "missing"}
            if target.is_file():
                backup = self.tx_dir / "backup" / f"{index:02d}-{target.name}"
                shutil.copy2(target, backup)
                item.update({"previous": "present", "backup": str(backup), "previous_sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
            files_meta.append(item)
        self.receipt["files"] = files_meta
        self._write_receipt()

    def _stage(self) -> None:
        assert self.tx_dir is not None
        stage_root = self.tx_dir / "stage"
        for index, (name, source, _) in enumerate(self.files):
            self.failpoint(f"stage:{name}")
            target = stage_root / f"{index:02d}-{source.name}"
            shutil.copyfile(source, target)
            os.chmod(target, 0o644)
            with target.open("rb") as handle:
                os.fsync(handle.fileno())
            if MARKER not in target.read_text(errors="replace").splitlines() or target.read_bytes() != source.read_bytes():
                raise PlatformError(f"staged file validation failed: {name}")
        self.failpoint("stage:complete")

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _atomic_copy(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".maho-platform.", dir=str(target.parent))
        tmp = Path(tmp_name)
        try:
            with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
                shutil.copyfileobj(src, dst)
                dst.flush()
                os.fsync(dst.fileno())
            os.chmod(tmp, 0o644)
            if os.geteuid() == 0:
                os.chown(tmp, 0, 0)
            os.replace(tmp, target)
            self._fsync_dir(target.parent)
        finally:
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _commit_files(self) -> None:
        assert self.tx_dir is not None
        stage_root = self.tx_dir / "stage"
        for index, (name, _, target) in enumerate(self.files):
            self.failpoint(f"commit:{name}")
            self._atomic_copy(stage_root / f"{index:02d}-{self.files[index][1].name}", target)
        self.failpoint("commit:complete")
        for name, source, target in self.files:
            if not self._exact(source, target):
                raise PlatformError(f"committed file verification failed: {name}")

    def _verify_provider(self, unit: str, *, enabled: bool) -> None:
        if enabled and self._systemctl("is-enabled", "--quiet", unit).returncode != 0:
            raise PlatformError(f"provider not enabled: {unit}")
        if not self._active(unit):
            raise PlatformError(f"provider not active: {unit}")

    def _activate_one(self, label: str, argv: list[str], unit: str, *, enabled: bool) -> None:
        self.failpoint(f"activate:{label}")
        self._systemctl(*argv, check=True)
        self._verify_provider(unit, enabled=enabled)
        changes = self.receipt.setdefault("service_changes", [])
        assert isinstance(changes, list)
        changes.append({"provider": label, "unit": unit, "command": argv, "verified": True})
        self._write_receipt()

    def _activate(self) -> None:
        self._systemctl("daemon-reload", check=True)
        self._activate_one("timesyncd", ["enable", "--now", "systemd-timesyncd.service"], "systemd-timesyncd.service", enabled=True)
        self._activate_one("oomd", ["enable", "--now", "systemd-oomd.service"], "systemd-oomd.service", enabled=True)
        self._activate_one("zram", ["start", "systemd-zram-setup@zram0.service"], "systemd-zram-setup@zram0.service", enabled=False)
        self._activate_one("rtkit", ["start", "rtkit-daemon.service"], "rtkit-daemon.service", enabled=False)
        self._activate_one("scrub", ["enable", "--now", "maho-btrfs-scrub-root.timer"], "maho-btrfs-scrub-root.timer", enabled=True)

    def _restore_enabled(self, unit: str, previous: str, errors: list[str]) -> None:
        current = self._enabled_state(unit)
        try:
            if previous == "enabled-runtime":
                if current != "enabled-runtime":
                    if current.startswith("enabled"):
                        self._systemctl("disable", unit, check=True)
                    self._systemctl("enable", "--runtime", unit, check=True)
            elif previous.startswith("enabled") and not current.startswith("enabled"):
                self._systemctl("enable", unit, check=True)
            elif previous == "disabled" and current.startswith("enabled"):
                self._systemctl("disable", unit, check=True)
        except PlatformError as exc:
            errors.append(str(exc))

    def _rollback(self) -> bool:
        assert self.tx_dir is not None
        rb = self.receipt.setdefault("rollback", {"attempted": True, "ok": None, "errors": []})
        assert isinstance(rb, dict)
        rb["attempted"] = True
        errors: list[str] = []
        files_meta = self.receipt.get("files", [])
        assert isinstance(files_meta, list)
        for item in reversed(files_meta):
            assert isinstance(item, dict)
            target = Path(str(item["target"]))
            try:
                if item.get("previous") == "present":
                    self._atomic_copy(Path(str(item["backup"])), target)
                elif target.exists() or target.is_symlink():
                    target.unlink()
                    self._fsync_dir(target.parent)
            except OSError as exc:
                errors.append(f"file rollback failed {target}: {exc}")
        try:
            self._systemctl("daemon-reload", check=True)
        except PlatformError as exc:
            errors.append(str(exc))
        previous = self.receipt.get("previous_runtime_state", {})
        service_state = previous.get("services", {}) if isinstance(previous, dict) else {}
        for unit in reversed(self.providers):
            state = service_state.get(unit, {}) if isinstance(service_state, dict) else {}
            was_active = bool(state.get("active")) if isinstance(state, dict) else False
            try:
                active = self._active(unit)
                if was_active and not active:
                    self._systemctl("start", unit, check=True)
                elif not was_active and active:
                    self._systemctl("stop", unit, check=True)
            except PlatformError as exc:
                errors.append(str(exc))
            previous_enabled = str(state.get("enabled", "unknown")) if isinstance(state, dict) else "unknown"
            self._restore_enabled(unit, previous_enabled, errors)
        restored_identity = self.state_identity()
        previous_identity = str(self.receipt.get("previous_state_identity") or "")
        rb["restored_state_identity"] = restored_identity
        rb["matches_previous_state_identity"] = bool(previous_identity and restored_identity == previous_identity)
        if previous_identity and restored_identity != previous_identity:
            errors.append("rollback state identity does not match the captured pre-transaction state")
        rb["ok"] = not errors
        rb["errors"] = errors
        self._write_receipt()
        return not errors

    def _cleanup_stage(self) -> None:
        if self.tx_dir is None:
            return
        shutil.rmtree(self.tx_dir / "stage", ignore_errors=True)
        for _, _, target in self.files:
            try:
                for child in target.parent.glob(".maho-platform.*"):
                    if child.is_file() or child.is_symlink():
                        child.unlink()
            except OSError:
                pass

    def _prune_transactions(self) -> None:
        root = self.state_root / "transactions"
        if not root.is_dir():
            return
        dirs = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True)
        for old in dirs[KEEP_TRANSACTIONS:]:
            if self.tx_dir is None or old != self.tx_dir:
                shutil.rmtree(old, ignore_errors=True)

    def install(self) -> int:
        self.require_authority()
        self._acquire_lock()
        self._new_transaction()
        committed = False
        try:
            errors = self.preflight(check_lock=False)
            if errors:
                raise PlatformError("preflight failed: " + "; ".join(errors))
            self.receipt["preflight"] = {"ok": True, "errors": []}
            self._capture_backup()
            self._stage()
            self._commit_files()
            committed = True
            self._activate()
            verification = self.verify_state(require_services=True)
            if verification:
                raise PlatformError("verification failed: " + "; ".join(verification))
            self.receipt["resulting_state_identity"] = self.state_identity()
            self.receipt["verification"] = {"ok": True, "errors": []}
            self.receipt["status"] = "committed"
            self.receipt["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self._write_receipt()
            print(f"PASS  platform transaction {self.receipt['transaction_id']}")
            print(f"PASS  receipt {self.tx_dir / 'receipt.json'}")
            print("INFO  no graphical session, portal, or keyring service was restarted")
            return 0
        except Exception as exc:
            message = str(exc)
            if "preflight" not in self.receipt:
                self.receipt["preflight"] = {"ok": False, "errors": [message]}
            self.receipt["status"] = "failed"
            self.receipt["failure"] = message
            self.receipt["verification"] = {"ok": False, "errors": [message]}
            rollback_ok = True
            if committed or bool(self.receipt.get("files")):
                rollback_ok = self._rollback()
            else:
                rb = self.receipt.get("rollback")
                if isinstance(rb, dict):
                    rb.update({"attempted": False, "ok": True, "errors": []})
            try:
                self.receipt["resulting_state_identity"] = self.state_identity()
            except Exception as identity_exc:
                self.receipt["resulting_state_identity"] = None
                self.receipt["resulting_state_identity_error"] = str(identity_exc)
            self.receipt["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self._write_receipt()
            suffix = "" if rollback_ok else "; rollback degraded - inspect receipt"
            print(f"maho-platform-install: {message}{suffix}", file=sys.stderr)
            return 1
        finally:
            self._cleanup_stage()
            self._write_receipt()
            self._prune_transactions()
            if self.lock_handle is not None:
                try:
                    fcntl.flock(self.lock_handle.fileno(), fcntl.LOCK_UN)
                finally:
                    self.lock_handle.close()

    def verify_state(self, *, require_services: bool) -> list[str]:
        errors: list[str] = []
        for name, source, target in self.files:
            if not self._exact(source, target):
                errors.append(f"managed file mismatch: {name}")
        if require_services:
            for unit in ("systemd-timesyncd.service", "systemd-oomd.service", "maho-btrfs-scrub-root.timer"):
                if self._systemctl("is-enabled", "--quiet", unit).returncode != 0 or not self._active(unit):
                    errors.append(f"provider not enabled and active: {unit}")
            for unit in ("rtkit-daemon.service", "systemd-zram-setup@zram0.service"):
                if not self._active(unit):
                    errors.append(f"provider not active: {unit}")
        return errors

    def status(self) -> int:
        errors = self.verify_state(require_services=True)
        if errors:
            for error in errors:
                print(f"FAIL  {error}")
            return 1
        print("PASS  Maho platform managed files exactly match candidate policy")
        print("PASS  timesyncd, oomd, zram, RTKit, and scrub timer provider states")
        return 0

    def uninstall(self) -> int:
        self.require_authority()
        for _, _, target in self.files:
            if target.exists() or target.is_symlink():
                if not self._managed(target):
                    raise PlatformError(f"refusing unmanaged file: {target}")
        for _, _, target in self.files:
            if target.exists() or target.is_symlink():
                target.unlink()
        self._systemctl("daemon-reload", check=True)
        print("PASS  removed Maho-owned platform policy")
        print("INFO  provider service states were deliberately left unchanged")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maho-platform-install")
    parser.add_argument("command", choices=("preflight", "install", "status", "uninstall"))
    args = parser.parse_args(argv)
    root = Path(os.environ.get("MAHO_ROOT") or Path(__file__).resolve().parent.parent)
    installer = PlatformInstaller(root)
    try:
        if args.command == "preflight":
            errors = installer.preflight()
            if errors:
                for error in errors:
                    print(f"FAIL  {error}")
                return 1
            print("PASS  Maho platform transactional preflight")
            return 0
        if args.command == "install":
            return installer.install()
        if args.command == "status":
            return installer.status()
        return installer.uninstall()
    except PlatformError as exc:
        print(f"maho-platform-install: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
