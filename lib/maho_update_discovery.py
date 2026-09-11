#!/usr/bin/env python3
"""Isolated Arch update discovery that never refreshes the live Pacman database."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence

from maho_update_state import create_transaction, new_transaction_id

PACMAN = "/usr/bin/pacman"
LIVE_DB = Path("/var/lib/pacman")
_PACKAGE = re.compile(r"[a-zA-Z0-9@._+:-]+")
_UPGRADE = re.compile(r"^(\S+)\s+(\S+)\s+->\s+(\S+)$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class DiscoveryResult:
    transaction: dict[str, Any]
    isolated_db: str
    candidate_count: int
    security_metadata_source: str | None
    notifications_emitted: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class IsolatedPacmanDiscovery:
    """The only production command authority used by update discovery."""

    def __init__(
        self,
        isolated_root: str | os.PathLike[str],
        *,
        installed_db: str | os.PathLike[str] = LIVE_DB / "local",
        runner: Callable[[Sequence[str]], CommandResult] | None = None,
    ) -> None:
        root = Path(isolated_root)
        if not root.is_absolute():
            raise ValueError("isolated discovery root must be absolute")
        root = root.resolve(strict=False)
        live = LIVE_DB.resolve(strict=False)
        if root == live or live in root.parents or root in live.parents:
            raise ValueError("isolated discovery root overlaps the live Pacman database")
        self.root = root
        self.db = root / "db"
        self.cache = root / "cache"
        self.log = root / "pacman.log"
        self.installed_db = Path(installed_db)
        self.runner = runner or self._system_run
        self.commands: list[tuple[str, ...]] = []

    def prepare(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.db.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.cache.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = self.db / "local"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(self.installed_db, destination, symlinks=False)

    @property
    def refresh_command(self) -> tuple[str, ...]:
        return (
            PACMAN, "--sync", "--refresh", "--dbpath", str(self.db),
            "--cachedir", str(self.cache), "--logfile", str(self.log), "--noconfirm",
        )

    @property
    def upgrades_command(self) -> tuple[str, ...]:
        return (PACMAN, "--query", "--upgrades", "--dbpath", str(self.db))

    def info_command(self, names: Sequence[str]) -> tuple[str, ...]:
        if not names or any(_PACKAGE.fullmatch(name) is None for name in names):
            raise ValueError("candidate package name is invalid")
        return (PACMAN, "--sync", "--info", "--dbpath", str(self.db), "--", *names)

    def _allowed(self, command: Sequence[str]) -> bool:
        argv = tuple(command)
        if argv in {self.refresh_command, self.upgrades_command}:
            return True
        prefix = (PACMAN, "--sync", "--info", "--dbpath", str(self.db), "--")
        return argv[: len(prefix)] == prefix and len(argv) > len(prefix) and all(
            _PACKAGE.fullmatch(name) is not None for name in argv[len(prefix):]
        )

    def run(self, command: Sequence[str]) -> CommandResult:
        if not self._allowed(command):
            raise PermissionError(f"update discovery command is not allowlisted: {tuple(command)!r}")
        if str(LIVE_DB) in command:
            raise PermissionError("live Pacman database cannot be a discovery command target")
        self.commands.append(tuple(command))
        return self.runner(tuple(command))

    @staticmethod
    def _system_run(command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(command), check=False, text=True, capture_output=True,
            env={"PATH": "/usr/bin", "LC_ALL": "C"},
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _parse_size(value: str) -> int:
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s+(B|KiB|MiB|GiB)", value.strip())
    if match is None:
        raise ValueError(f"unsupported Pacman size: {value!r}")
    multipliers = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
    return int(float(match.group(1)) * multipliers[match.group(2)])


def parse_upgrades(output: str) -> list[tuple[str, str, str]]:
    candidates: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        if not line.strip():
            continue
        match = _UPGRADE.fullmatch(line.strip())
        if match is None or _PACKAGE.fullmatch(match.group(1)) is None:
            raise ValueError(f"ambiguous Pacman upgrade output: {line!r}")
        name, installed, candidate = match.groups()
        if name in seen or installed == candidate:
            raise ValueError("ambiguous duplicate or unchanged candidate")
        seen.add(name)
        candidates.append((name, installed, candidate))
    return candidates


def parse_sync_info(output: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, str] = {}
    for line in [*output.splitlines(), ""]:
        if not line.strip():
            if current:
                required = {"Name", "Version", "Repository", "Download Size", "Installed Size"}
                if not required.issubset(current):
                    raise ValueError("Pacman package metadata is incomplete")
                name = current["Name"]
                if _PACKAGE.fullmatch(name) is None or name in records:
                    raise ValueError("Pacman package metadata identity is ambiguous")
                records[name] = {
                    "version": current["Version"],
                    "repository": current["Repository"],
                    "download_size": _parse_size(current["Download Size"]),
                    "installed_size": _parse_size(current["Installed Size"]),
                }
                current = {}
            continue
        if line[:1].isspace():
            continue
        key, separator, value = line.partition(":")
        if separator:
            current[key.strip()] = value.strip()
    return records


def package_roles(name: str) -> list[str]:
    roles: set[str] = set()
    if name in {"linux-cachyos", "linux-cachyos-lts"}:
        roles.update({"kernel", "initramfs", "boot-artifacts"})
        roles.add("primary-kernel" if name == "linux-cachyos" else "fallback-kernel")
    if name in {"linux-cachyos-headers", "linux-cachyos-lts-headers"}:
        roles.update({"kernel-headers", "dkms"})
        roles.add("primary-headers" if name == "linux-cachyos-headers" else "fallback-headers")
    lowered = name.lower()
    if "nvidia" in lowered:
        roles.update({"nvidia", "dkms", "initramfs"})
    elif "dkms" in lowered:
        roles.add("dkms")
    if name == "maho-os" or name.startswith("maho-"):
        roles.add("maho-runtime")
    return sorted(roles)


def activation_requirements(packages: Sequence[Mapping[str, Any]]) -> list[str]:
    roles = {role for package in packages for role in package.get("roles", [])}
    requirements: set[str] = set()
    if "maho-runtime" in roles:
        requirements.add("maho-runtime-release")
    if roles & {"kernel", "dkms", "initramfs"}:
        requirements.update({"initramfs", "boot-artifacts", "restart"})
    return sorted(requirements)


def discover_updates(
    backend: IsolatedPacmanDiscovery,
    *,
    source_revision: str,
    security_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    recovery_generation_id: str | None = None,
    now: datetime | None = None,
    entropy: str | None = None,
) -> DiscoveryResult:
    backend.prepare()
    refreshed = backend.run(backend.refresh_command)
    if refreshed.returncode != 0:
        raise RuntimeError(f"isolated synchronization failed: {refreshed.stderr.strip()}")
    queried = backend.run(backend.upgrades_command)
    if queried.returncode not in {0, 1}:
        raise RuntimeError(f"isolated update comparison failed: {queried.stderr.strip()}")
    candidates = parse_upgrades(queried.stdout)
    if not candidates:
        raise LookupError("no coherent update candidates were discovered")
    metadata_result = backend.run(backend.info_command([item[0] for item in candidates]))
    if metadata_result.returncode != 0:
        raise RuntimeError(f"candidate metadata lookup failed: {metadata_result.stderr.strip()}")
    metadata = parse_sync_info(metadata_result.stdout)
    evidence = security_evidence or {}
    packages: list[dict[str, Any]] = []
    trusted_sources: set[str] = set()
    for name, installed, candidate in candidates:
        info = metadata.get(name)
        if info is None or info["version"] != candidate:
            raise ValueError(f"candidate metadata does not bind exact version: {name}")
        security = evidence.get(name, {})
        trusted = security.get("trusted") is True and isinstance(security.get("source"), str)
        if trusted:
            trusted_sources.add(security["source"])
        packages.append({
            "name": name,
            "installed_version": installed,
            "candidate_version": candidate,
            "repository": info["repository"],
            "download_size": info["download_size"],
            "installed_size": info["installed_size"],
            "security_relevant": bool(security.get("relevant")) if trusted else False,
            "roles": package_roles(name),
        })
    transaction = create_transaction(
        transaction_id=new_transaction_id(now=now, entropy=entropy),
        source_revision=source_revision,
        packages=packages,
        activation_requirements=activation_requirements(packages),
        recovery_generation_id=recovery_generation_id,
        now=now,
    )
    return DiscoveryResult(
        transaction=transaction,
        isolated_db=str(backend.db),
        candidate_count=len(packages),
        security_metadata_source=",".join(sorted(trusted_sources)) or None,
    )
