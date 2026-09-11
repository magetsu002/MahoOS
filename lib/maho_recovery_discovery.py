#!/usr/bin/env python3
"""Read-only Btrfs/Snapper/Limine discovery for Guardian G3."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from maho_recovery_generation import (
    BootEvidence,
    RecoveryGenerationReport,
    SnapshotEvidence,
    build_report,
    evaluate_generation,
)


@dataclass(frozen=True)
class ProbeResult:
    available: bool
    returncode: int
    stdout: str = ""
    stderr: str = ""


class Probe(Protocol):
    def run(self, argv: Sequence[str]) -> ProbeResult: ...
    def read_text(self, path: str) -> str | None: ...
    def read_bytes(self, path: str) -> bytes | None: ...


class SystemProbe:
    """Execute only the exact read-only command shapes used by G3 discovery."""

    _PACKAGE = re.compile(r"[A-Za-z0-9@._+:-]+")
    _SNAPPER_CONFIG = re.compile(r"[A-Za-z0-9._-]+")
    _SNAPSHOT_PATH = re.compile(r"/(?:[A-Za-z0-9._@+-]+/)*\.snapshots/[1-9][0-9]*/snapshot")
    _FINDMNT_OUTPUT = "TARGET,SOURCE,FSTYPE,FSROOT,UUID"

    @classmethod
    def _allowed(cls, args: tuple[str, ...]) -> bool:
        if len(args) == 6 and args[0:3] == ("findmnt", "--json", "--target"):
            return args[3] in {"/", "/home", "/run/maho-recovery-overlay/lower"} and args[4:] == ("--output", cls._FINDMNT_OUTPUT)
        if len(args) == 3 and args[0:2] == ("pacman", "-Q"):
            return bool(cls._PACKAGE.fullmatch(args[2]))
        if len(args) == 5 and args[0:2] == ("pacman", "--root"):
            return (
                bool(cls._SNAPSHOT_PATH.fullmatch(args[2]))
                and args[3] == "-Q"
                and bool(cls._PACKAGE.fullmatch(args[4]))
            )
        if len(args) == 5 and args[0:3] == ("snapper", "--jsonout", "--config"):
            return bool(cls._SNAPPER_CONFIG.fullmatch(args[3])) and args[4] == "get-config"
        if len(args) == 6 and args[0:3] == ("snapper", "--jsonout", "--config"):
            return (
                bool(cls._SNAPPER_CONFIG.fullmatch(args[3]))
                and args[4:] == ("list", "--disable-used-space")
            )
        if len(args) == 6 and args[0:4] == ("btrfs", "property", "get", "-ts"):
            return bool(cls._SNAPSHOT_PATH.fullmatch(args[4])) and args[5] == "ro"
        return False

    def run(self, argv: Sequence[str]) -> ProbeResult:
        args = tuple(str(x) for x in argv)
        if not self._allowed(args):
            raise RuntimeError(f"G3 refused non-read-only command shape: {args!r}")
        try:
            proc = subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return ProbeResult(False, 127, "", str(exc))
        return ProbeResult(True, proc.returncode, proc.stdout, proc.stderr)

    def read_text(self, path: str) -> str | None:
        try:
            return pathlib.Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None

    def read_bytes(self, path: str) -> bytes | None:
        try:
            return pathlib.Path(path).read_bytes()
        except OSError:
            return None


class FixtureProbe:
    """Command/file fixture adapter; command keys use exact argv joined by NUL."""

    def __init__(self, fixture: Mapping[str, Any]):
        self.fixture = fixture
        self.commands: list[tuple[str, ...]] = []

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> "FixtureProbe":
        return cls(json.loads(pathlib.Path(path).read_text()))

    def run(self, argv: Sequence[str]) -> ProbeResult:
        args = tuple(str(x) for x in argv)
        self.commands.append(args)
        key = "\0".join(args)
        item = self.fixture.get("commands", {}).get(key)
        if item is None:
            return ProbeResult(False, 127, "", "fixture command unavailable")
        return ProbeResult(
            bool(item.get("available", True)),
            int(item.get("returncode", 0)),
            str(item.get("stdout", "")),
            str(item.get("stderr", "")),
        )

    def read_text(self, path: str) -> str | None:
        value = self.fixture.get("files", {}).get(path)
        if value is None:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def read_bytes(self, path: str) -> bytes | None:
        value = self.fixture.get("files", {}).get(path)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode()
        return json.dumps(value, sort_keys=True).encode()


def _json_result(result: ProbeResult) -> Any | None:
    if not result.available or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _findmnt_mount(probe: Probe, target: str) -> Mapping[str, Any] | None:
    data = _json_result(
        probe.run(("findmnt", "--json", "--target", target, "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID"))
    )
    filesystems = data.get("filesystems") if isinstance(data, Mapping) else None
    if not isinstance(filesystems, list) or not filesystems or not isinstance(filesystems[0], Mapping):
        return None
    return filesystems[0]


def _root_mount_evidence(probe: Probe) -> tuple[Mapping[str, Any] | None, bool]:
    """Return authoritative root evidence, unwrapping only Maho recovery OverlayFS.

    Ordinary OverlayFS roots remain unsupported. The lower Btrfs mount is trusted
    only when the explicit Maho recovery kernel flag is present, matching the
    initrd contract that created the temporary writable layer.
    """
    root = _findmnt_mount(probe, "/")
    if not root or root.get("fstype") != "overlay":
        return root, False

    cmdline = (probe.read_text("/proc/cmdline") or "").split()
    if "maho.recovery_snapshot=1" not in cmdline:
        return root, False

    lower = _findmnt_mount(probe, "/run/maho-recovery-overlay/lower")
    if not lower or lower.get("fstype") != "btrfs":
        return root, False
    return lower, True


def _package(probe: Probe, name: str) -> tuple[bool, str | None]:
    result = probe.run(("pacman", "-Q", name))
    if not result.available or result.returncode != 0:
        return False, None
    parts = result.stdout.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0] != name:
        return True, None
    return True, parts[1]


def _parse_simple_config(text: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not text:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def _snapper_config(probe: Probe, config_name: str) -> Mapping[str, Any] | None:
    data = _json_result(probe.run(("snapper", "--jsonout", "--config", config_name, "get-config")))
    if isinstance(data, Mapping):
        if "SUBVOLUME" in data:
            return data
        rows = data.get(config_name) or data.get("config") or data.get("rows")
        if isinstance(rows, list):
            normalized: dict[str, Any] = {}
            for row in rows:
                if isinstance(row, Mapping):
                    key = row.get("key")
                    if isinstance(key, str):
                        normalized[key] = row.get("value")
            return normalized or None
    return None


def _snapshots(probe: Probe, config_name: str) -> list[Mapping[str, Any]] | None:
    data = _json_result(
        probe.run(("snapper", "--jsonout", "--config", config_name, "list", "--disable-used-space"))
    )
    if not isinstance(data, Mapping):
        return None
    rows = data.get(config_name)
    if not isinstance(rows, list):
        return None
    return [row for row in rows if isinstance(row, Mapping)]


def _userdata(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, str):
        result: dict[str, str] = {}
        for token in value.split(","):
            if "=" in token:
                k, v = token.split("=", 1)
                result[k.strip()] = v.strip()
        return result
    return {}


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _snapshot_evidence(
    config_name: str,
    row: Mapping[str, Any],
    all_rows: list[Mapping[str, Any]],
    *,
    probed_read_only: bool | None,
) -> SnapshotEvidence | None:
    sid = _int(row.get("number"))
    if sid is None or sid <= 0:
        return None
    stype = row.get("type") if isinstance(row.get("type"), str) else None
    pre = _int(row.get("pre-number"))
    desc = row.get("description") if isinstance(row.get("description"), str) else None
    package_relation = "unknown"
    if stype == "post":
        package_relation = "post-linked" if pre and any(_int(x.get("number")) == pre for x in all_rows) else "broken"
    elif stype == "pre":
        linked = any(_int(x.get("pre-number")) == sid and x.get("type") == "post" for x in all_rows)
        package_relation = "pre-linked" if linked else "broken"
    elif stype == "single":
        package_relation = "not-applicable"
    listed_read_only = _bool(row.get("read-only"))
    return SnapshotEvidence(
        config_name=config_name,
        snapshot_id=sid,
        creation_time=row.get("date") if isinstance(row.get("date"), str) else None,
        subvolume=row.get("subvolume") if isinstance(row.get("subvolume"), str) else None,
        snapshot_type=stype,
        cleanup=row.get("cleanup") if isinstance(row.get("cleanup"), str) else None,
        description=desc,
        userdata=_userdata(row.get("userdata")),
        pre_number=pre,
        active=_bool(row.get("active")),
        default=_bool(row.get("default")),
        read_only=listed_read_only if listed_read_only is not None else probed_read_only,
        package_transaction=package_relation,
    )


def _snapshot_read_only(probe: Probe, snapper_subvolume: str | None, snapshot_id: int) -> bool | None:
    if not isinstance(snapper_subvolume, str) or not snapper_subvolume.startswith("/"):
        return None
    base = snapper_subvolume.rstrip("/")
    path = f"{base}/.snapshots/{snapshot_id}/snapshot" if base else f"/.snapshots/{snapshot_id}/snapshot"
    result = probe.run(("btrfs", "property", "get", "-ts", path, "ro"))
    if not result.available or result.returncode != 0:
        return None
    match = re.fullmatch(r"\s*ro=(true|false)\s*", result.stdout, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _home_scope(root: Mapping[str, Any] | None, home: Mapping[str, Any] | None) -> str:
    if not root or not home:
        return "unknown"
    root_source, root_fsroot = root.get("source"), root.get("fsroot")
    home_source, home_fsroot = home.get("source"), home.get("fsroot")
    if not all(isinstance(x, str) and x for x in (root_source, root_fsroot, home_source, home_fsroot)):
        return "unknown"
    if (root_source, root_fsroot) != (home_source, home_fsroot):
        return "excluded"
    return "included"


def _manifest_paths(probe: Probe, limine_cfg: Mapping[str, str]) -> list[str]:
    machine_id = (probe.read_text("/etc/machine-id") or "").strip()
    esp = limine_cfg.get("ESP_PATH")
    candidates: list[str] = []
    roots = [esp] if esp else ["/boot", "/efi", "/boot/efi", "/limine"]
    if machine_id:
        for root in roots:
            if root:
                candidates.append(f"{root.rstrip('/')}/{machine_id}/limine_history/snapshots.json")
        candidates.append(f"/var/cache/boot/{machine_id}/lss/snapshots.json")
    return candidates


def _load_manifest(probe: Probe, limine_cfg: Mapping[str, str]) -> tuple[Mapping[str, Any] | None, str | None]:
    for path in _manifest_paths(probe, limine_cfg):
        text = probe.read_text(path)
        if text is None:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None, path
        if isinstance(data, Mapping):
            return data, path
        return None, path
    return None, None


def _manifest_snapshot_id(entry: Mapping[str, Any]) -> int | None:
    for key in ("snapshotId", "snapshotID", "snapshotNumber", "number", "id"):
        value = _int(entry.get(key))
        if value is not None:
            return value
    snapper_id = entry.get("snapperID")
    if isinstance(snapper_id, Mapping):
        for key in ("snapshotId", "snapshotID", "snapshotNumber", "number", "id"):
            value = _int(snapper_id.get(key))
            if value is not None:
                return value
    return None


def _snapshot_package(probe: Probe, snapshot_id: int, name: str) -> str | None:
    root = f"/.snapshots/{snapshot_id}/snapshot"
    result = probe.run(("pacman", "--root", root, "-Q", name))
    if not result.available or result.returncode != 0:
        return None
    parts = result.stdout.strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0] != name:
        return None
    return parts[1]


def _image_detail(kernel: Mapping[str, Any], limine_key: str, *, initramfs: bool = False) -> Mapping[str, Any] | None:
    rows = kernel.get("imageDetails")
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, Mapping) or str(row.get("limineKey") or "").upper() != limine_key:
            continue
        name = str(row.get("fileName") or "").lower()
        if initramfs and not ("initramfs" in name or "initrd" in name):
            continue
        return row
    return None


def _boot_path_from_image(detail: Mapping[str, Any] | None) -> str | None:
    if not isinstance(detail, Mapping):
        return None
    raw = detail.get("snapshotFilePathLine")
    if not isinstance(raw, str) or not raw.startswith("/"):
        return None
    props = detail.get("properties")
    resource = props.get("PATH_RESOURCE") if isinstance(props, Mapping) else None
    if resource not in {None, "", "boot():", "$boot():"}:
        return None
    return "boot():" + raw


def _package_from_kernel(kernel: Mapping[str, Any]) -> str | None:
    pkg = _first_str(kernel, ("package", "kernelPackage", "kernelName", "name"))
    if pkg in {"linux-cachyos", "linux-cachyos-lts"}:
        return pkg
    detail = _image_detail(kernel, "KERNEL_PATH")
    name = str(detail.get("fileName") or "") if isinstance(detail, Mapping) else ""
    if name == "vmlinuz-linux-cachyos-lts":
        return "linux-cachyos-lts"
    if name == "vmlinuz-linux-cachyos":
        return "linux-cachyos"
    if pkg:
        low = pkg.lower()
        if "cachyos-lts" in low:
            return "linux-cachyos-lts"
        if "cachyos" in low:
            return "linux-cachyos"
    return pkg


def _real_snapshot_cmdline_matches(manifest: Mapping[str, Any], kernel: Mapping[str, Any], snapshot_id: int) -> bool:
    props = manifest.get("properties")
    snapshots_path = props.get("SNAPSHOTS_PATH") if isinstance(props, Mapping) else None
    if not isinstance(snapshots_path, str) or not snapshots_path.startswith("/"):
        return False
    expected = f"rootflags=subvol={snapshots_path.rstrip('/')}/{snapshot_id}/snapshot"
    rows = kernel.get("cmdlineDetails")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        value = row.get("snapshotCmdline")
        if isinstance(value, str) and expected in value.split():
            return True
    return False


def _real_snapshot_cmdline_has_overlay(kernel: Mapping[str, Any]) -> bool:
    rows = kernel.get("cmdlineDetails")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        value = row.get("snapshotCmdline")
        if isinstance(value, str) and "maho.recovery_snapshot=1" in value.split():
            return True
    return False


def _first_str(mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _artifact_from_config(lines: Any, needle: str) -> str | None:
    if not isinstance(lines, list):
        return None
    for value in lines:
        if not isinstance(value, str):
            continue
        lower = value.lower()
        if needle in lower and (":" in value or "=" in value):
            return value.split(":" if ":" in value else "=", 1)[1].strip()
    return None


_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_SHA256_IN_PATH = re.compile(r"(?:^|[_-])sha256[_-]([0-9a-fA-F]{64})(?:$|[._-])")


def _boot_root(configured_root: str | None, manifest_path: str | None) -> str | None:
    if isinstance(configured_root, str) and configured_root.startswith("/"):
        return os.path.normpath(configured_root)
    if not manifest_path:
        return None
    for prefix in ("/boot/efi", "/boot", "/efi", "/limine"):
        if manifest_path == prefix or manifest_path.startswith(prefix + "/"):
            return prefix
    return None


def _artifact_local_path(raw: str | None, boot_root: str | None) -> str | None:
    if not raw or not boot_root:
        return None
    root = os.path.normpath(boot_root)
    if raw.startswith("boot():/"):
        candidate = os.path.normpath(os.path.join(root, raw[len("boot():/"):]))
    elif raw.startswith("/"):
        candidate = os.path.normpath(raw)
    else:
        return None
    try:
        if os.path.commonpath((root, candidate)) != root:
            return None
    except ValueError:
        return None
    return candidate


def _digest_value(mapping: Mapping[str, Any], keys: Sequence[str]) -> str | None:
    value = _first_str(mapping, keys)
    return value.lower() if value and _HEX64.fullmatch(value) else None


def _digest_from_path(path: str | None) -> str | None:
    if not path:
        return None
    match = _SHA256_IN_PATH.search(path)
    return match.group(1).lower() if match else None


def _verify_artifact(
    probe: Probe,
    raw_path: str | None,
    boot_root: str | None,
    explicit_digest: str | None,
) -> tuple[str | None, str | None, bool | None]:
    expected = explicit_digest or _digest_from_path(raw_path)
    local = _artifact_local_path(raw_path, boot_root)
    if expected is None or local is None:
        return expected, None, None
    data = probe.read_bytes(local)
    if data is None:
        return expected, None, False
    observed = hashlib.sha256(data).hexdigest()
    return expected, observed, observed == expected


def _boot_evidence(
    probe: Probe,
    manifest: Mapping[str, Any] | None,
    manifest_path: str | None,
    configured_boot_root: str | None,
    snapshot_id: int,
) -> BootEvidence:
    if not manifest:
        return BootEvidence(source="unavailable", reason="limine-snapper-sync manifest unavailable or malformed")
    entries = manifest.get("snapshotEntries")
    if not isinstance(entries, list):
        return BootEvidence(source=manifest_path or "limine-snapper-sync-manifest", reason="manifest snapshotEntries missing")
    matched = next((x for x in entries if isinstance(x, Mapping) and _manifest_snapshot_id(x) == snapshot_id), None)
    if not isinstance(matched, Mapping):
        return BootEvidence(source=manifest_path or "limine-snapper-sync-manifest", reason="snapshot has no Limine manifest entry")
    kernels = matched.get("kernelEntries")
    if not isinstance(kernels, list) or not kernels:
        return BootEvidence(source=manifest_path or "limine-snapper-sync-manifest", snapshot_id=snapshot_id, reason="kernel entries missing")

    normalized = [k for k in kernels if isinstance(k, Mapping)]

    def score(k: Mapping[str, Any]) -> int:
        pkg = _package_from_kernel(k)
        return 2 if pkg == "linux-cachyos" else 1 if pkg == "linux-cachyos-lts" else 0

    kernel = max(normalized, key=score) if normalized else {}
    real_schema = isinstance(matched.get("snapperID"), Mapping)
    lines = kernel.get("allInConfig")
    pkg = _package_from_kernel(kernel)
    version = _snapshot_package(probe, snapshot_id, pkg) if real_schema and pkg else _first_str(kernel, ("version", "kernelVersion"))

    kernel_detail = _image_detail(kernel, "KERNEL_PATH") if real_schema else None
    initramfs_detail = _image_detail(kernel, "MODULE_PATH", initramfs=True) if real_schema else None
    kernel_path = (
        _boot_path_from_image(kernel_detail)
        if real_schema
        else _first_str(kernel, ("kernelPath", "kernel_path", "linux")) or _artifact_from_config(lines, "kernel_path")
    )
    initramfs = (
        _boot_path_from_image(initramfs_detail)
        if real_schema
        else _first_str(kernel, ("initramfsPath", "initrdPath", "modulePath", "module_path")) or _artifact_from_config(lines, "module_path")
    )

    manifest_verified = matched.get("filesVerified")
    if not isinstance(manifest_verified, bool):
        manifest_verified = kernel.get("filesVerified") if isinstance(kernel.get("filesVerified"), bool) else None
    manifest_coherent = matched.get("artifactsCoherent")
    if not isinstance(manifest_coherent, bool):
        manifest_coherent = kernel.get("artifactsCoherent") if isinstance(kernel.get("artifactsCoherent"), bool) else None

    boot_root = _boot_root(configured_boot_root, manifest_path)
    kernel_explicit = (
        _digest_from_path(str(kernel_detail.get("fileHashName") or ""))
        if real_schema and isinstance(kernel_detail, Mapping)
        else _digest_value(kernel, ("kernelSha256", "kernelSHA256", "kernel_sha256"))
    )
    init_explicit = (
        _digest_from_path(str(initramfs_detail.get("fileHashName") or ""))
        if real_schema and isinstance(initramfs_detail, Mapping)
        else _digest_value(kernel, ("initramfsSha256", "initramfsSHA256", "initramfs_sha256", "initrdSha256"))
    )
    kernel_expected, kernel_observed, kernel_ok = _verify_artifact(probe, kernel_path, boot_root, kernel_explicit)
    init_expected, init_observed, init_ok = _verify_artifact(probe, initramfs, boot_root, init_explicit)
    files_verified = bool(kernel_ok is True and init_ok is True and manifest_verified is not False)
    if kernel_ok is None or init_ok is None:
        files_verified = None

    if real_schema:
        relation_ok = _real_snapshot_cmdline_matches(manifest, kernel, snapshot_id)
        recovery_overlay_flagged = _real_snapshot_cmdline_has_overlay(kernel)
        coherent = True if files_verified is True and relation_ok else False
    else:
        raw_overlay = kernel.get("recoveryOverlayFlagged")
        recovery_overlay_flagged = raw_overlay if isinstance(raw_overlay, bool) else None
        coherent = (
            True
            if files_verified is True and manifest_coherent is True
            else False
            if files_verified is False or manifest_coherent is False
            else None
        )

    manifest_uuid = _first_str(manifest, ("filesystemUuid", "filesystemUUID", "fsUuid", "fsUUID", "uuid"))
    return BootEvidence(
        source=manifest_path or "limine-snapper-sync-manifest",
        entry_id=_first_str(matched, ("entryId", "name", "title")) or f"snapshot-{snapshot_id}",
        kernel_package=pkg,
        kernel_version=version,
        kernel_path=kernel_path,
        initramfs_path=initramfs,
        kernel_sha256_expected=kernel_expected,
        kernel_sha256_observed=kernel_observed,
        initramfs_sha256_expected=init_expected,
        initramfs_sha256_observed=init_observed,
        snapshot_id=snapshot_id,
        filesystem_uuid=manifest_uuid,
        files_verified=files_verified,
        artifacts_coherent=coherent,
        recovery_overlay_flagged=recovery_overlay_flagged,
        reason=None if coherent is True else "saved boot artifacts are not fully hash-verified and coherent",
    )


def _current_snapshot_id(rows: list[Mapping[str, Any]] | None, root: Mapping[str, Any] | None) -> int | None:
    if rows:
        for row in rows:
            if row.get("active") is True:
                sid = _int(row.get("number"))
                if sid and sid > 0:
                    return sid
    fsroot = root.get("fsroot") if root else None
    if isinstance(fsroot, str):
        match = re.search(r"(?:^|/)\.snapshots/(\d+)/snapshot(?:/|$)", fsroot)
        if match:
            return int(match.group(1))
    return None


def discover_recovery_generations(policy: Mapping[str, Any], probe: Probe) -> RecoveryGenerationReport:
    kernel = policy.get("kernel", {}) if isinstance(policy.get("kernel"), Mapping) else {}
    boot_policy = policy.get("boot", {}) if isinstance(policy.get("boot"), Mapping) else {}
    states = policy.get("system_states", {}) if isinstance(policy.get("system_states"), Mapping) else {}
    config_name = states.get("root_snapper_config") if isinstance(states.get("root_snapper_config"), str) else "root"

    root, recovery_overlay_active = _root_mount_evidence(probe)
    home = _findmnt_mount(probe, "/home")
    primary = kernel.get("primary_package") if isinstance(kernel.get("primary_package"), str) else "linux-cachyos"
    fallback = kernel.get("fallback_package") if isinstance(kernel.get("fallback_package"), str) else "linux-cachyos-lts"
    primary_present, primary_version = _package(probe, primary)
    lts_present, lts_version = _package(probe, fallback)
    snapper_present, snapper_version = _package(probe, "snapper")
    snap_pac_present, snap_pac_version = _package(probe, "snap-pac")
    limine_present, limine_version = _package(probe, "limine")
    lss_present, lss_version = _package(probe, "limine-snapper-sync")

    lss_config = _parse_simple_config(probe.read_text("/etc/limine-snapper-sync.conf"))
    lss_config.update(_parse_simple_config(probe.read_text("/etc/default/limine")))
    configured_snapper = lss_config.get("SNAPPER_CONFIG_NAME")
    wrong_snapper_config = bool(configured_snapper and configured_snapper != config_name)

    snapper_cfg = None if wrong_snapper_config or not snapper_present else _snapper_config(probe, config_name)
    rows = None if snapper_cfg is None else _snapshots(probe, config_name)
    manifest, manifest_path = _load_manifest(probe, lss_config) if lss_present else (None, None)

    fs_uuid = root.get("uuid") if root and isinstance(root.get("uuid"), str) else None
    root_source = root.get("source") if root and isinstance(root.get("source"), str) else None
    root_fsroot = root.get("fsroot") if root and isinstance(root.get("fsroot"), str) else None
    root_fstype = root.get("fstype") if root and isinstance(root.get("fstype"), str) else None
    snapper_subvolume = snapper_cfg.get("SUBVOLUME") if snapper_cfg and isinstance(snapper_cfg.get("SUBVOLUME"), str) else None
    current_id = _current_snapshot_id(rows, root)
    home_scope = _home_scope(root, home)

    platform = {
        "root_fstype": root_fstype,
        "root_source": root_source,
        "root_fsroot": root_fsroot,
        "root_filesystem_uuid": fs_uuid,
        "recovery_overlay_active": recovery_overlay_active,
        "home_scope": home_scope,
        "snapper_config": config_name,
        "snapper_config_available": snapper_cfg is not None,
        "snapper_config_mismatch": wrong_snapper_config,
        "snapper_present": snapper_present,
        "snapper_version": snapper_version,
        "snap_pac_present": snap_pac_present,
        "snap_pac_version": snap_pac_version,
        "limine_present": limine_present,
        "limine_version": limine_version,
        "limine_snapper_sync_present": lss_present,
        "limine_snapper_sync_version": lss_version,
        "limine_manifest_path": manifest_path,
        "limine_manifest_available": manifest is not None,
        "primary_kernel_present": primary_present,
        "primary_kernel_version": primary_version,
        "lts_kernel_present": lts_present,
        "lts_kernel_version": lts_version,
        "current_snapshot_id": current_id,
        "boot_state_transaction_required": bool(boot_policy.get("boot_state_transaction_required", False)),
        "kernel_snapshot_restore_certified": bool(boot_policy.get("kernel_update_snapshot_restore_certified", False)),
    }

    generations = []
    for row in rows or []:
        sid = _int(row.get("number"))
        probed_read_only = _snapshot_read_only(probe, snapper_subvolume, sid) if sid and sid > 0 else None
        snapshot = _snapshot_evidence(
            config_name,
            row,
            rows or [],
            probed_read_only=probed_read_only,
        )
        if snapshot is None:
            continue
        boot = _boot_evidence(
            probe,
            manifest,
            manifest_path,
            lss_config.get("ESP_PATH"),
            snapshot.snapshot_id,
        )
        userdata = snapshot.userdata
        known_good = userdata.get("maho.known_good", "").lower() in {"1", "yes", "true"}
        generations.append(
            evaluate_generation(
                snapshot=snapshot,
                filesystem_uuid=fs_uuid,
                root_source=root_source,
                root_fsroot=root_fsroot,
                root_fstype=root_fstype,
                snapper_subvolume=snapper_subvolume,
                home_scope=home_scope,
                boot=boot,
                current_snapshot_id=current_id,
                lts_kernel_present=lts_present,
                expected_kernel_packages=(primary, fallback),
                boot_state_transaction_required=bool(boot_policy.get("boot_state_transaction_required", False)),
                known_good=known_good,
            )
        )

    return build_report(
        platform=platform,
        generations=generations,
        kernel_restore_certified=bool(boot_policy.get("kernel_update_snapshot_restore_certified", False)),
    )
