#!/usr/bin/env python3
"""Read-only AUR update discovery bound to Maho's canonical repository universe."""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Callable, Sequence

_ROW = re.compile(r"^(\S+)\s+(\S+)\s+->\s+(\S+)(?:\s+\[[^]]+\])?$")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class AurCandidate:
    name: str
    installed_version: str
    candidate_version: str
    source_kind: str = "aur"


@dataclass(frozen=True)
class AurDiscovery:
    schema_version: int
    kind: str
    observed_at: str
    pacman_config: str
    pacman_config_sha256: str
    packages: tuple[AurCandidate, ...]

    def as_dict(self) -> dict:
        data = asdict(self)
        data["packages"] = [asdict(item) for item in self.packages]
        return data


def parse_yay_upgrades(output: str) -> list[AurCandidate]:
    rows: list[AurCandidate] = []
    names: set[str] = set()
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = _ROW.fullmatch(line)
        if match is None:
            raise ValueError(f"ambiguous yay upgrade output: {line!r}")
        name, installed, candidate = match.groups()
        if name in names or installed == candidate:
            raise ValueError("ambiguous duplicate or unchanged AUR candidate")
        names.add(name)
        rows.append(AurCandidate(name, installed, candidate))
    return sorted(rows, key=lambda item: item.name)


def _run_system(command: Sequence[str]) -> CommandResult:
    completed = subprocess.run(list(command), text=True, capture_output=True, check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def discover_aur_updates(
    *,
    config_path: str | Path,
    yay: str = "/usr/bin/yay",
    pacman: str = "/usr/bin/pacman",
    runner: Callable[[Sequence[str]], CommandResult] | None = None,
    now: dt.datetime | None = None,
) -> AurDiscovery:
    raw_config = Path(config_path)
    if raw_config.is_symlink():
        raise ValueError("canonical Maho Pacman config cannot be a symlink")
    config = raw_config.resolve(strict=False)
    if not config.is_file():
        raise ValueError("canonical Maho Pacman config is unavailable")
    run = runner or _run_system
    query = (yay, "--config", str(config), "-Qua")
    result = run(query)
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"AUR discovery failed: {(result.stderr or result.stdout).strip()}")
    candidates = parse_yay_upgrades(result.stdout)
    for candidate in candidates:
        owned = run((pacman, "--config", str(config), "--sync", "--info", "--", candidate.name))
        if owned.returncode == 0:
            raise RuntimeError(f"AUR discovery violated repository authority:{candidate.name}")
    current = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    return AurDiscovery(
        schema_version=1,
        kind="maho-aur-discovery",
        observed_at=current.isoformat(timespec="seconds").replace("+00:00", "Z"),
        pacman_config=str(config),
        pacman_config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        packages=tuple(candidates),
    )


def main() -> None:
    parser=argparse.ArgumentParser(prog="maho-aur-discovery")
    parser.add_argument("--config", default="/etc/maho/pacman.conf")
    parser.add_argument("--yay", default="/usr/bin/yay")
    parser.add_argument("--pacman", default="/usr/bin/pacman")
    parser.add_argument("--json", action="store_true")
    args=parser.parse_args()
    try:
        value=discover_aur_updates(config_path=args.config,yay=args.yay,pacman=args.pacman)
    except (ValueError,RuntimeError) as exc:
        raise SystemExit(f"maho-aur-discovery: {exc}") from exc
    payload=value.as_dict()
    if args.json:
        print(json.dumps(payload,sort_keys=True,separators=(",",":")))
        return
    print("Maho AUR discovery")
    print(f"Repository authority: {payload['pacman_config']}")
    if not payload['packages']:
        print("AUR updates: none")
        return
    for item in payload['packages']:
        print(f"{item['name']}: {item['installed_version']} -> {item['candidate_version']}")

if __name__=="__main__": main()
