#!/usr/bin/env python3
"""Turn isolated AUR build outputs into Maho-owned exact artifacts."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping, Sequence
import uuid

from maho_update_discovery import package_roles
from maho_update_effects import aur_build_provenance, classify_artifact

_EXCLUDED_DIRS = {".git", "pkg", "src"}
_EXCLUDED_NAMES = {".SRCINFO"}
_EXCLUDED_GLOBS = ("*.pkg.tar.*", "*.log", ".maho-*")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_tree_sha256(stage: Path) -> str:
    root = stage.resolve(strict=True)
    records: list[bytes] = []
    for path in sorted(root.rglob("*"), key=lambda item: str(item.relative_to(root))):
        rel = path.relative_to(root)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        if path.name in _EXCLUDED_NAMES or any(fnmatch.fnmatch(path.name, pattern) for pattern in _EXCLUDED_GLOBS):
            continue
        if path.is_symlink():
            target = os.readlink(path)
            if target.startswith("/"):
                raise ValueError(f"AUR source contains absolute symlink:{rel}")
            resolved = (path.parent / target).resolve(strict=False)
            if root != resolved and root not in resolved.parents:
                raise ValueError(f"AUR source symlink escapes staged source:{rel}")
            records.append(b"L\0" + str(rel).encode() + b"\0" + target.encode() + b"\n")
            continue
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"unsupported AUR source inode:{rel}")
        records.append(
            b"F\0" + str(rel).encode() + b"\0" + str(path.stat().st_mode & 0o777).encode() +
            b"\0" + hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n"
        )
    if not any(record.startswith(b"F\0PKGBUILD\0") for record in records):
        raise ValueError("staged AUR source lacks PKGBUILD")
    return hashlib.sha256(b"".join(records)).hexdigest()


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), text=True, capture_output=True, check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def _parse_info(output: str) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"Name", "Version"}:
            fields[key.strip()] = value.strip()
    name, version = fields.get("Name", ""), fields.get("Version", "")
    if not name or not version:
        raise ValueError("built package identity is unavailable")
    return name, version


def _parse_list(output: str, expected_name: str) -> list[str]:
    files: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        name, sep, path = line.partition(" ")
        if sep != " " or name != expected_name or not path.startswith("/"):
            raise ValueError("built package file inventory is ambiguous")
        files.append(path)
    if not files:
        raise ValueError("built package file inventory is empty")
    return files


def artifact_identity(payload: Mapping[str, Any]) -> str:
    identity = {
        "name": payload["name"],
        "version": payload["version"],
        "sha256": payload["sha256"],
        "provenance": payload["provenance"],
        "effects": payload["effects"],
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return "aurpkg-" + hashlib.sha256(encoded).hexdigest()


def inspect_artifact(
    package: Path,
    *,
    pacman: str,
    pacman_config: Path,
    source_sha256: str,
    receipt_path: Path,
    package_base: str | None = None,
) -> dict[str, Any]:
    path = package.resolve(strict=True)
    info = _run((pacman, "--query", "--file", "--info", "--", str(path)))
    if info.returncode != 0:
        raise ValueError(f"cannot inspect built package identity:{path.name}")
    name, version = _parse_info(info.stdout)
    installed_query = _run((pacman, "--query", "--", name))
    if installed_query.returncode == 0:
        fields = installed_query.stdout.strip().split()
        if len(fields) != 2 or fields[0] != name or not fields[1]:
            raise ValueError(f"installed package identity is ambiguous:{name}")
        installed_version = fields[1]
    else:
        installed_version = "<not-installed>"
    if installed_version == version:
        raise ValueError(f"built package does not change installed version:{name}")
    owned = _run((pacman, "--config", str(pacman_config), "--sync", "--info", "--", name))
    if owned.returncode == 0:
        raise PermissionError(f"repository-owned package cannot enter AUR authority:{name}")
    listing = _run((pacman, "--query", "--file", "--list", "--", str(path)))
    if listing.returncode != 0:
        raise ValueError(f"cannot inspect built package file inventory:{name}")
    files = _parse_list(listing.stdout, name)
    provenance = aur_build_provenance(
        package_base=package_base or name,
        source_sha256=source_sha256,
        build_receipt=str(receipt_path),
    )
    effects = classify_artifact(package_name=name, roles=package_roles(name), files=files)
    payload: dict[str, Any] = {
        "name": name,
        "installed_version": installed_version,
        "version": version,
        "path": str(path),
        "sha256": sha256_file(path),
        "size": path.stat().st_size,
        "provenance": provenance,
        "effects": effects,
        "route": "boot-critical" if effects["classification"] == "boot-critical" else "normal",
        "automatic_install": False,
    }
    payload["artifact_id"] = artifact_identity(payload)
    return payload


def _write_private(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def record_build(
    *,
    state_root: Path,
    stage: Path,
    preflight: Mapping[str, Any],
    status: str,
    phase: str,
    pacman_config: Path,
    pacman: str,
) -> tuple[dict[str, Any], int]:
    stage = stage.resolve(strict=True)
    if pacman_config.is_symlink():
        raise ValueError("canonical Pacman config cannot be a symlink")
    config = pacman_config.resolve(strict=True)
    source_digest = source_tree_sha256(stage)
    metadata_path = stage / ".maho-aur-metadata.json"
    aur_metadata: dict[str, Any] | None = None
    if metadata_path.is_file() and not metadata_path.is_symlink():
        try:
            raw_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"AUR fetch metadata is invalid:{exc}") from exc
        if not isinstance(raw_metadata, Mapping):
            raise ValueError("AUR fetch metadata is invalid")
        required = ("name", "version", "package_base", "aur_git_commit", "repository_config_sha256")
        if any(not isinstance(raw_metadata.get(key), str) or not raw_metadata[key] for key in required):
            raise ValueError("AUR fetch metadata is incomplete")
        commit = str(raw_metadata["aur_git_commit"])
        if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
            raise ValueError("AUR fetch Git commit is invalid")
        aur_metadata = dict(raw_metadata)
    receipt_dir = state_root / "aur-builds"
    receipt_path = receipt_dir / f"build-{source_digest[:20]}.json"
    artifacts: list[dict[str, Any]] = []
    rejection: str | None = None
    result_status = status
    exit_code = 0
    if status == "verified" and phase == "complete":
        outputs = sorted(
            p for p in stage.glob("*.pkg.tar.*")
            if p.is_file() and not p.is_symlink() and not p.name.endswith(".sig")
        )
        if not outputs:
            result_status = "failed"
            rejection = "isolated build produced no package artifacts"
            exit_code = 4
        else:
            try:
                artifacts = [
                    inspect_artifact(
                        path, pacman=pacman, pacman_config=config,
                        source_sha256=source_digest, receipt_path=receipt_path,
                        package_base=str(aur_metadata["package_base"]) if aur_metadata else None,
                    )
                    for path in outputs
                ]
            except (PermissionError, ValueError) as exc:
                result_status = "rejected"
                rejection = str(exc)
                artifacts = []
                exit_code = 4
            if exit_code == 0 and aur_metadata is not None:
                target = (aur_metadata["name"], aur_metadata["version"])
                if not any((item["name"], item["version"]) == target for item in artifacts):
                    result_status = "rejected"
                    rejection = "built artifacts do not contain exact fetched AUR candidate:" + target[0] + "=" + target[1]
                    artifacts = []
                    exit_code = 4
    routes = sorted({item["route"] for item in artifacts})
    payload: dict[str, Any] = {
        "version": 2,
        "kind": "aur-isolated-build",
        "at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "status": result_status,
        "phase": phase,
        "stage": str(stage),
        "pkgbuild_sha256": preflight.get("sha256"),
        "source_tree_sha256": source_digest,
        "aur_metadata": aur_metadata,
        "preflight_risk": preflight.get("risk"),
        "preflight_score": preflight.get("score"),
        "repository_authority": {
            "config": str(config),
            "sha256": sha256_file(config),
        },
        "sandbox": {
            "host_root": "read-only",
            "host_home": "hidden",
            "root_home": "hidden",
            "runtime_user_dir": "hidden",
            "process_namespace": "isolated",
            "capabilities": "dropped",
            "fetch_network": "available",
            "build_network": "isolated",
        },
        "packages": artifacts,
        "routes": routes,
        "automatic_install": False,
        "installation_authority": "maho-update-only",
    }
    if rejection:
        payload["rejection"] = rejection
    _write_private(receipt_path, payload)
    payload["receipt_path"] = str(receipt_path)
    return payload, exit_code


def main() -> None:
    parser = argparse.ArgumentParser(prog="maho-aur-artifact")
    parser.add_argument("--state-root", required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--preflight-json", required=True)
    parser.add_argument("--status", required=True, choices=("verified", "failed"))
    parser.add_argument("--phase", required=True)
    parser.add_argument("--pacman-config", required=True)
    parser.add_argument("--pacman", default="/usr/bin/pacman")
    args = parser.parse_args()
    try:
        preflight = json.loads(args.preflight_json)
        if not isinstance(preflight, Mapping):
            raise ValueError("preflight record is invalid")
        payload, code = record_build(
            state_root=Path(args.state_root), stage=Path(args.stage), preflight=preflight,
            status=args.status, phase=args.phase, pacman_config=Path(args.pacman_config), pacman=args.pacman,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"maho-aur-artifact: {exc}") from exc
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    raise SystemExit(code)

if __name__ == "__main__":
    main()
