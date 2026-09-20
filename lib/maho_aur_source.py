#!/usr/bin/env python3
"""Fetch exact AUR source trees under canonical Maho repository authority."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Sequence

_PACKAGE = re.compile(r"[a-zA-Z0-9@._+:-]+")
_SHA40 = re.compile(r"[0-9a-f]{40}")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class AurSource:
    path: str
    name: str
    version: str
    package_base: str
    aur_git_commit: str
    repository_config_sha256: str
    fetched_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "name": self.name,
            "version": self.version,
            "package_base": self.package_base,
            "aur_git_commit": self.aur_git_commit,
            "repository_config_sha256": self.repository_config_sha256,
            "fetched_at": self.fetched_at,
        }


def _system_run(command: Sequence[str], cwd: Path | None = None) -> CommandResult:
    completed = subprocess.run(
        list(command), cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _parse_yay_info(output: str) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"Name", "Version"}:
            fields[key.strip()] = value.strip()
    name, version = fields.get("Name", ""), fields.get("Version", "")
    if not name or not version:
        raise ValueError("AUR metadata does not expose exact name/version")
    return name, version


def _pkgbase(source: Path) -> str:
    srcinfo = source / ".SRCINFO"
    if srcinfo.is_file() and not srcinfo.is_symlink():
        for line in srcinfo.read_text(encoding="utf-8", errors="strict").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "pkgbase":
                candidate = value.strip()
                if _PACKAGE.fullmatch(candidate):
                    return candidate
    candidate = source.name
    if _PACKAGE.fullmatch(candidate) is None:
        raise ValueError("AUR package base identity is unavailable")
    return candidate


def fetch_aur_source(
    package: str,
    *,
    expected_version: str | None,
    cache_root: str | Path,
    config_path: str | Path,
    yay: str = "/usr/bin/yay",
    pacman: str = "/usr/bin/pacman",
    git: str = "/usr/bin/git",
    runner: Callable[[Sequence[str], Path | None], CommandResult] | None = None,
    now: dt.datetime | None = None,
) -> AurSource:
    if _PACKAGE.fullmatch(package) is None:
        raise ValueError("AUR package name is invalid")
    raw_config = Path(config_path)
    if raw_config.is_symlink():
        raise ValueError("canonical Maho Pacman config cannot be a symlink")
    config = raw_config.resolve(strict=False)
    if not config.is_file():
        raise ValueError("canonical Maho Pacman config is unavailable")
    run = runner or _system_run

    repo = run((pacman, "--config", str(config), "--sync", "--info", "--", package), None)
    if repo.returncode == 0:
        raise PermissionError(f"repository-owned package cannot be fetched as AUR source:{package}")
    info = run((yay, "--config", str(config), "--sync", "--info", "--aur", "--", package), None)
    if info.returncode != 0:
        raise RuntimeError(f"AUR metadata lookup failed:{(info.stderr or info.stdout).strip()}")
    observed_name, observed_version = _parse_yay_info(info.stdout)
    if observed_name != package:
        raise ValueError("AUR metadata package identity drifted")
    if expected_version is not None and observed_version != expected_version:
        raise ValueError(f"AUR metadata version drifted:{package}:{expected_version}->{observed_version}")

    cache = Path(cache_root).expanduser().resolve(strict=False)
    fetch_root = cache / "sources"
    fetch_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(fetch_root, 0o700)
    temporary = Path(tempfile.mkdtemp(prefix=f".fetch-{package}-", dir=fetch_root))
    try:
        fetched = run((yay, "--getpkgbuild", "--aur", "--config", str(config), "--noconfirm", "--", package), temporary)
        if fetched.returncode != 0:
            raise RuntimeError(f"AUR source fetch failed:{(fetched.stderr or fetched.stdout).strip()}")
        candidates = sorted(path for path in temporary.iterdir() if path.is_dir() and (path / "PKGBUILD").is_file())
        if len(candidates) != 1:
            raise ValueError("AUR source fetch did not yield exactly one PKGBUILD tree")
        source = candidates[0]
        base = _pkgbase(source)
        revision = run((git, "rev-parse", "HEAD"), source)
        commit = revision.stdout.strip() if revision.returncode == 0 else ""
        if _SHA40.fullmatch(commit) is None:
            raise ValueError("AUR source Git identity is unavailable")
        stamp = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        metadata = {
            "schema_version": 1,
            "kind": "maho-aur-source",
            "name": package,
            "version": observed_version,
            "package_base": base,
            "aur_git_commit": commit,
            "repository_config": str(config),
            "repository_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
            "fetched_at": stamp,
        }
        destination = fetch_root / f"source-{base}-{commit[:12]}"
        if destination.exists():
            existing = destination / ".maho-aur-metadata.json"
            if not existing.is_file() or json.loads(existing.read_text(encoding="utf-8")) != metadata:
                raise ValueError("existing AUR source identity conflicts with fetched source")
            return AurSource(str(destination), package, observed_version, base, commit, metadata["repository_config_sha256"], stamp)
        metadata_path = source / ".maho-aur-metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(metadata_path, 0o600)
        shutil.move(str(source), destination)
        os.chmod(destination, 0o700)
        return AurSource(str(destination), package, observed_version, base, commit, metadata["repository_config_sha256"], stamp)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-aur-source")
    parser.add_argument("package")
    parser.add_argument("--expected-version")
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--config", default="/etc/maho/pacman.conf")
    parser.add_argument("--yay", default="/usr/bin/yay")
    parser.add_argument("--pacman", default="/usr/bin/pacman")
    parser.add_argument("--git", default="/usr/bin/git")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        result = fetch_aur_source(
            args.package, expected_version=args.expected_version, cache_root=args.cache_root,
            config_path=args.config, yay=args.yay, pacman=args.pacman, git=args.git,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, PermissionError, RuntimeError) as exc:
        raise SystemExit(f"maho-aur-source: {exc}") from exc
    if args.json:
        print(json.dumps(result.as_dict(), sort_keys=True, separators=(",", ":")))
    else:
        print(result.path)

if __name__ == "__main__":
    main()
