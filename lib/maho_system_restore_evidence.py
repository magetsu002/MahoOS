#!/usr/bin/env python3
"""Read-only evidence collection for the bounded MahoOS L3 restore provider."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat as statmod
import subprocess
from typing import Any, Mapping, Protocol, Sequence


@dataclass(frozen=True)
class CommandResult:
    available: bool
    returncode: int
    stdout: str
    stderr: str = ""


class EvidenceProbe(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...
    def stat(self, path: str) -> os.stat_result | None: ...
    def read_text(self, path: str) -> str | None: ...


class SystemEvidenceProbe:
    """Allow only the exact read-only provider inspection used by V1 L3."""

    _ALLOWED = {
        ("pacman", "-Q", "limine-snapper-sync"),
        ("pacman", "-Qkk", "limine-snapper-sync"),
        ("pacman", "-Qo", "/usr/bin/limine-snapper-restore"),
    }
    _READABLE = {
        "/etc/limine-snapper-sync.conf",
        "/etc/default/limine",
        "/proc/cmdline",
    }
    _STATABLE = {"/usr/bin/limine-snapper-restore"}

    def run(self, argv: Sequence[str]) -> CommandResult:
        args = tuple(str(x) for x in argv)
        if args not in self._ALLOWED:
            raise RuntimeError(f"L3 evidence probe refused command shape: {args!r}")
        try:
            proc = subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return CommandResult(False, 127, "", str(exc))
        return CommandResult(True, proc.returncode, proc.stdout, proc.stderr)

    def stat(self, path: str) -> os.stat_result | None:
        if path not in self._STATABLE:
            raise RuntimeError(f"L3 evidence probe refused stat path: {path!r}")
        try:
            return os.stat(path, follow_symlinks=True)
        except OSError:
            return None

    def read_text(self, path: str) -> str | None:
        if path not in self._READABLE:
            raise RuntimeError(f"L3 evidence probe refused read path: {path!r}")
        try:
            return Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return None


def parse_provider_config(*texts: str | None) -> dict[str, str]:
    """Parse simple scalar assignments; later files override earlier ones."""
    result: dict[str, str] = {}
    for text in texts:
        if not isinstance(text, str):
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "+=" in line:
                continue
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
            if not match:
                continue
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            result[match.group(1)] = value
    return result


def collect_provider_evidence(policy: Mapping[str, Any], probe: EvidenceProbe | None = None) -> dict[str, Any]:
    probe = probe or SystemEvidenceProbe()
    recovery = policy.get("recovery") if isinstance(policy.get("recovery"), Mapping) else {}
    expected = recovery.get("system_restore_provider") if isinstance(recovery.get("system_restore_provider"), Mapping) else {}
    package = expected.get("package") if isinstance(expected.get("package"), str) else ""
    path = expected.get("command") if isinstance(expected.get("command"), str) else ""

    version = ""
    package_query = probe.run(("pacman", "-Q", "limine-snapper-sync"))
    if package_query.available and package_query.returncode == 0:
        fields = package_query.stdout.strip().split()
        if len(fields) == 2 and fields[0] == package:
            version = fields[1]

    owner_query = probe.run(("pacman", "-Qo", "/usr/bin/limine-snapper-restore"))
    package_owns_command = bool(
        owner_query.available
        and owner_query.returncode == 0
        and f"is owned by {package} " in owner_query.stdout
    )
    integrity_query = probe.run(("pacman", "-Qkk", "limine-snapper-sync"))
    package_files_ok = bool(
        integrity_query.available
        and integrity_query.returncode == 0
        and re.search(r"\b0 altered files\b", integrity_query.stdout)
    )

    st = probe.stat(path) if path else None
    mode = statmod.S_IMODE(st.st_mode) if st is not None else None
    regular = bool(st is not None and statmod.S_ISREG(st.st_mode))
    uid = st.st_uid if st is not None else None

    config = parse_provider_config(
        probe.read_text("/etc/limine-snapper-sync.conf"),
        probe.read_text("/etc/default/limine"),
    )
    return {
        "path": path,
        "package": package,
        "version": version,
        "uid": uid,
        "mode": mode,
        "regular_file": regular,
        "package_owns_command": package_owns_command,
        "package_files_ok": package_files_ok,
        "cmdline": probe.read_text("/proc/cmdline") or "",
        "config": config,
    }
