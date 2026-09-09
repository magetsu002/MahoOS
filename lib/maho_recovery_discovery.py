#!/usr/bin/env python3
"""Read-only Btrfs/Snapper/Limine discovery for Guardian G3.

SystemProbe has an explicit allowlist and never invokes snapshot/boot mutation
commands.  FixtureProbe uses the same interface so CI requires neither Btrfs
nor root privileges.
"""
from __future__ import annotations

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


class SystemProbe:
    SAFE_COMMANDS = {"findmnt", "snapper", "pacman"}
    SAFE_PACMAN = {"-Q"}
    SAFE_SNAPPER_COMMANDS = {"get-config", "list"}

    def run(self, argv: Sequence[str]) -> ProbeResult:
        args = tuple(str(x) for x in argv)
        if not args or args[0] not in self.SAFE_COMMANDS:
            raise RuntimeError(f"G3 refused non-read-only command: {args!r}")
        if args[0] == "pacman" and (len(args) < 2 or args[1] not in self.SAFE_PACMAN):
            raise RuntimeError(f"G3 refused mutating pacman command: {args!r}")
        if args[0] == "snapper" and not any(x in self.SAFE_SNAPPER_COMMANDS for x in args):
            raise RuntimeError(f"G3 refused mutating snapper command: {args!r}")
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


def _json_result(result: ProbeResult) -> Any | None:
    if not result.available or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return None


def _findmnt_mount(probe: Probe, target: str) -> Mapping[str, Any] | None:
    data = _json_result(probe.run(("findmnt", "--json", "--target", target, "--output", "TARGET,SOURCE,FSTYPE,FSROOT,UUID")))
    filesystems = data.get("filesystems") if isinstance(data, Mapping) else None
    if not isinstance(filesystems, list) or not filesystems or not isinstance(filesystems[0], Mapping):
        return None
    return filesystems[0]


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
        # Current Snapper emits either a direct key/value object or a table-like
        # object. Normalize both without accepting guessed plain-text output.
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
    data = _json_result(probe.run(("snapper", "--jsonout", "--config", config_name, "list", "--disable-used-space")))
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


def _snapshot_evidence(config_name: str, row: Mapping[str, Any], all_rows: list[Mapping[str, Any]]) -> SnapshotEvidence | None:
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
        read_only=_bool(row.get("read-only")),
        package_transaction=package_relation,
    )


def _home_scope(root: Mapping[str, Any] | None, home: Mapping[str, Any] | None) -> str:
    if not root or not home:
        return "unknown"
    root_source, root_fsroot = root.get("source"), root.get("fsroot")
    home_source, home_fsroot = home.get("source"), home.get("fsroot")
    if not all(isinstance(x, str) and x for x in (root_source, root_fsroot, home_source, home_fsroot)):
        return "unknown"
    # findmnt --target /home returns the containing mount. A distinct source or
    # Btrfs FSROOT proves /home is outside the root snapshot; the same mount
    # proves it is included in root scope.
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
    return None


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


def _boot_evidence(manifest: Mapping[str, Any] | None, manifest_path: str | None, snapshot_id: int, fs_uuid: str | None) -> BootEvidence:
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

    # Prefer the primary CachyOS kernel, otherwise a documented LTS fallback.
    normalized = [k for k in kernels if isinstance(k, Mapping)]
    def score(k: Mapping[str, Any]) -> int:
        text = json.dumps(k, sort_keys=True).lower()
        if "linux-cachyos\"" in text or "linux-cachyos " in text:
            return 2
        if "linux-cachyos-lts" in text:
            return 1
        return 0
    kernel = max(normalized, key=score) if normalized else {}
    lines = kernel.get("allInConfig")
    pkg = _first_str(kernel, ("package", "kernelPackage", "kernelName", "name"))
    version = _first_str(kernel, ("version", "kernelVersion"))
    kernel_path = _first_str(kernel, ("kernelPath", "kernel_path", "linux")) or _artifact_from_config(lines, "kernel_path")
    initramfs = _first_str(kernel, ("initramfsPath", "initrdPath", "modulePath", "module_path")) or _artifact_from_config(lines, "module_path")
    if pkg and pkg not in {"linux-cachyos", "linux-cachyos-lts"}:
        low = pkg.lower()
        pkg = "linux-cachyos-lts" if "cachyos-lts" in low else "linux-cachyos" if "cachyos" in low else pkg

    # Current manifests carry checksums/verification metadata in different
    # versions. Fixtures use the canonical fields below; unknown live schemas
    # fail closed instead of assuming success.
    verified = matched.get("filesVerified")
    if not isinstance(verified, bool):
        verified = kernel.get("filesVerified") if isinstance(kernel.get("filesVerified"), bool) else None
    coherent = matched.get("artifactsCoherent")
    if not isinstance(coherent, bool):
        coherent = kernel.get("artifactsCoherent") if isinstance(kernel.get("artifactsCoherent"), bool) else None
    manifest_uuid = _first_str(manifest, ("filesystemUuid", "filesystemUUID", "fsUuid", "fsUUID")) or fs_uuid
    return BootEvidence(
        source=manifest_path or "limine-snapper-sync-manifest",
        entry_id=_first_str(matched, ("entryId", "name", "title")) or f"snapshot-{snapshot_id}",
        kernel_package=pkg,
        kernel_version=version,
        kernel_path=kernel_path,
        initramfs_path=initramfs,
        snapshot_id=snapshot_id,
        filesystem_uuid=manifest_uuid,
        files_verified=verified,
        artifacts_coherent=coherent,
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

    root = _findmnt_mount(probe, "/")
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
        snapshot = _snapshot_evidence(config_name, row, rows or [])
        if snapshot is None:
            continue
        boot = _boot_evidence(manifest, manifest_path, snapshot.snapshot_id, fs_uuid)
        userdata = snapshot.userdata
        known_good = userdata.get("maho.known_good", "").lower() in {"1", "yes", "true"}
        generations.append(evaluate_generation(
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
        ))

    return build_report(
        platform=platform,
        generations=generations,
        kernel_restore_certified=bool(boot_policy.get("kernel_update_snapshot_restore_certified", False)),
    )
