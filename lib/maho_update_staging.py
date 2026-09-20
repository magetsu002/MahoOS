#!/usr/bin/env python3
"""Safe, resumable package staging for an exact Maho Update generation."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence

from maho_update_discovery import CommandResult, PACMAN
from maho_update_effects import aggregate_effects, classify_artifact, repository_provenance, validate_provenance
from maho_update_state import UpdateState, transition_transaction, validate_transaction

LIVE_DB = Path("/var/lib/pacman")
LIVE_CACHE = Path("/var/cache/pacman/pkg")
_PACKAGE = re.compile(r"[a-zA-Z0-9@._+:-]+")
_DIGEST = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class StagingResult:
    transaction: dict[str, Any]
    manifest: dict[str, Any] | None
    estimated_requirement: int
    available_bytes: int
    resumed: bool
    cleanup_removed: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class IsolatedPacmanStaging:
    """Bounded command authority for availability checks, downloads, and package inspection."""

    def __init__(
        self,
        isolated_db: str | os.PathLike[str],
        cache_root: str | os.PathLike[str],
        *,
        config_path: str | os.PathLike[str] = "/etc/pacman.conf",
        runner: Callable[[Sequence[str]], CommandResult] | None = None,
    ) -> None:
        self.db = self._safe_root(isolated_db, LIVE_DB, "staging database")
        self.cache = self._safe_root(cache_root, LIVE_CACHE, "staging cache")
        self.log = self.cache / "pacman-stage.log"
        self.config = Path(config_path).resolve(strict=False)
        if not self.config.is_absolute():
            raise ValueError("Pacman config path must be absolute")
        self.runner = runner or self._system_run
        self.commands: list[tuple[str, ...]] = []

    @staticmethod
    def _safe_root(value: str | os.PathLike[str], live: Path, name: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            raise ValueError(f"{name} must be absolute")
        path = path.resolve(strict=False)
        live = live.resolve(strict=False)
        if path == live or live in path.parents or path in live.parents:
            raise ValueError(f"{name} overlaps a live Pacman path")
        return path

    def _download_identity(self) -> tuple[int, int] | None:
        if os.geteuid() != 0:
            return None
        completed = subprocess.run(
            ("/usr/bin/pacman-conf", "--config", str(self.config), "DownloadUser"),
            check=False, text=True, capture_output=True,
            env={"PATH": "/usr/bin", "LC_ALL": "C"},
        )
        name = completed.stdout.strip() if completed.returncode == 0 else ""
        if not name:
            return None
        try:
            account = pwd.getpwnam(name)
        except KeyError as exc:
            raise RuntimeError("configured Pacman DownloadUser is unavailable") from exc
        return account.pw_uid, account.pw_gid

    def prepare(self) -> None:
        if not self.db.is_dir():
            raise ValueError("isolated synchronization database is unavailable")
        self.cache.mkdir(mode=0o755, parents=True, exist_ok=True)
        identity = self._download_identity()
        if identity is not None:
            os.chown(self.cache, *identity)
            os.chmod(self.cache, 0o755)

    def availability_command(self, targets: Sequence[str]) -> tuple[str, ...]:
        self._validate_targets(targets)
        return (
            PACMAN, "--config", str(self.config), "--sync", "--print", "--print-format", "%r\t%n\t%v", "--dbpath", str(self.db),
            "--", *targets,
        )

    def download_command(self, targets: Sequence[str]) -> tuple[str, ...]:
        self._validate_targets(targets)
        return (
            PACMAN, "--config", str(self.config), "--sync", "--downloadonly", "--noconfirm", "--dbpath", str(self.db),
            "--cachedir", str(self.cache), "--logfile", str(self.log), "--", *targets,
        )

    def list_command(self, package_path: Path) -> tuple[str, ...]:
        path = package_path.resolve(strict=False)
        if path.parent != self.cache or path.is_symlink() or ".pkg.tar." not in path.name:
            raise ValueError("package inspection path escapes isolated staging cache")
        return (PACMAN, "--query", "--file", "--list", "--", str(path))

    def info_command(self, package_path: Path) -> tuple[str, ...]:
        path = package_path.resolve(strict=False)
        if path.parent != self.cache or path.is_symlink() or ".pkg.tar." not in path.name:
            raise ValueError("package inspection path escapes isolated staging cache")
        return (PACMAN, "--query", "--file", "--info", "--", str(path))

    @staticmethod
    def _validate_targets(targets: Sequence[str]) -> None:
        if not targets:
            raise ValueError("exact staging targets are required")
        for target in targets:
            repository, slash, identity = target.partition("/")
            name, separator, version = identity.partition("=")
            if (
                slash != "/"
                or separator != "="
                or _PACKAGE.fullmatch(repository) is None
                or _PACKAGE.fullmatch(name) is None
                or not version
                or any(char.isspace() for char in version)
            ):
                raise ValueError("staging target must be an exact repository/name=version identity")

    def _allowed(self, command: Sequence[str]) -> bool:
        argv = tuple(command)
        if argv[:9] == (PACMAN, "--config", str(self.config), "--sync", "--print", "--print-format", "%r\t%n\t%v", "--dbpath", str(self.db)):
            try:
                marker = argv.index("--", 9)
                self._validate_targets(argv[marker + 1:])
                return marker == 9
            except (ValueError, IndexError):
                return False
        prefix = (
            PACMAN, "--config", str(self.config), "--sync", "--downloadonly", "--noconfirm", "--dbpath", str(self.db),
            "--cachedir", str(self.cache), "--logfile", str(self.log), "--",
        )
        if argv[: len(prefix)] == prefix:
            try:
                self._validate_targets(argv[len(prefix):])
                return True
            except ValueError:
                return False
        if argv[:5] in {
            (PACMAN, "--query", "--file", "--info", "--"),
            (PACMAN, "--query", "--file", "--list", "--"),
        } and len(argv) == 6:
            try:
                (self.info_command if argv[3] == "--info" else self.list_command)(Path(argv[5]))
                return True
            except ValueError:
                return False
        return False

    def run(self, command: Sequence[str]) -> CommandResult:
        if not self._allowed(command):
            raise PermissionError(f"update staging command is not allowlisted: {tuple(command)!r}")
        argv = tuple(command)
        if str(LIVE_DB) in argv or str(LIVE_CACHE) in argv:
            raise PermissionError("live Pacman paths cannot be staging targets")
        self.commands.append(argv)
        return self.runner(argv)

    @staticmethod
    def _system_run(command: Sequence[str]) -> CommandResult:
        completed = subprocess.run(
            list(command), check=False, text=True, capture_output=True,
            env={"PATH": "/usr/bin", "LC_ALL": "C"},
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _exact_targets(transaction: Mapping[str, Any]) -> list[str]:
    packages = validate_transaction(transaction)["package_generation"]["packages"]
    return [f"{item['repository']}/{item['name']}={item['candidate_version']}" for item in packages]


def _parse_availability(output: str) -> dict[str, tuple[str, str]]:
    available: dict[str, tuple[str, str]] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if (
            len(fields) != 3
            or _PACKAGE.fullmatch(fields[0]) is None
            or _PACKAGE.fullmatch(fields[1]) is None
            or not fields[2]
            or fields[1] in available
        ):
            raise ValueError("ambiguous package availability output")
        repository, name, version = fields
        available[name] = (repository, version)
    return available


def _parse_file_info(output: str) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"Name", "Version"}:
            fields[key.strip()] = value.strip()
    name, version = fields.get("Name"), fields.get("Version")
    if not name or _PACKAGE.fullmatch(name) is None or not version:
        raise ValueError("package file identity is unavailable")
    return name, version


def _parse_file_list(output: str, expected_name: str) -> list[str]:
    files: list[str] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        name, separator, path = line.partition(" ")
        if separator != " " or name != expected_name or not path.startswith("/"):
            raise ValueError("package file inventory is ambiguous")
        files.append(path.strip())
    if not files:
        raise ValueError("package file inventory is empty")
    return files


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(manifest: Mapping[str, Any], transaction: Mapping[str, Any], cache_root: Path) -> dict[str, Any]:
    transaction = validate_transaction(transaction)
    data = dict(manifest)
    schema = data.get("schema_version")
    if schema not in {1, 2} or data.get("transaction_id") != transaction["transaction_id"]:
        raise ValueError("staging manifest transaction identity is invalid")
    if data.get("package_generation_id") != transaction["package_generation"]["id"]:
        raise ValueError("staging manifest package generation is invalid")
    payloads = data.get("payloads")
    if not isinstance(payloads, list):
        raise ValueError("staging payload manifest is invalid")
    expected = {(item["name"], item["candidate_version"]) for item in transaction["package_generation"]["packages"]}
    observed: set[tuple[str, str]] = set()
    for payload in payloads:
        if not isinstance(payload, Mapping):
            raise ValueError("staging payload must be an object")
        identity = (payload.get("name"), payload.get("version"))
        path = Path(str(payload.get("path", ""))).resolve(strict=False)
        digest = payload.get("sha256")
        if identity in observed or identity not in expected:
            raise ValueError("staging payload identity is ambiguous")
        if path.parent != cache_root.resolve(strict=False) or path.is_symlink() or not path.is_file():
            raise ValueError("staging payload path is unsafe or unavailable")
        if not isinstance(digest, str) or _DIGEST.fullmatch(digest) is None or _sha256(path) != digest:
            raise ValueError("staging payload digest mismatch")
        if payload.get("size") != path.stat().st_size:
            raise ValueError("staging payload size mismatch")
        if schema >= 2:
            provenance = validate_provenance(payload.get("provenance", {}))
            verification = payload.get("signature_status")
            if provenance["kind"] == "repository" and verification != "verified-by-pacman":
                raise ValueError("repository staging payload lacks Pacman signature verification")
            if provenance["kind"] == "aur-built" and verification != "maho-isolated-build":
                raise ValueError("AUR staging payload lacks Maho isolated-build verification")
            effects = payload.get("effects")
            if not isinstance(effects, Mapping) or effects.get("classification") not in {"normal", "boot-critical"}:
                raise ValueError("staging payload effect analysis is invalid")
            if not isinstance(effects.get("files_sha256"), str) or _DIGEST.fullmatch(effects["files_sha256"]) is None:
                raise ValueError("staging payload file inventory digest is invalid")
            if not isinstance(effects.get("file_count"), int) or effects["file_count"] < 1:
                raise ValueError("staging payload file inventory count is invalid")
        observed.add(identity)
    if observed != expected:
        raise ValueError("staging manifest is incomplete")
    return data


def _manifest_path(cache: Path, generation_id: str) -> Path:
    return cache / f"manifest-{generation_id}.json"


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def cleanup_isolated_cache(cache: Path, keep: set[Path], *, max_remove_bytes: int = 1024**3) -> tuple[str, ...]:
    removed: list[str] = []
    removed_bytes = 0
    root = cache.resolve(strict=True)
    for candidate in sorted(cache.iterdir(), key=lambda item: item.name):
        resolved = candidate.resolve(strict=False)
        if resolved in keep or candidate.is_symlink() or not candidate.is_file():
            continue
        if ".pkg.tar." not in candidate.name and not candidate.name.endswith(".sig"):
            continue
        size = candidate.stat().st_size
        if removed_bytes + size > max_remove_bytes:
            break
        if resolved.parent != root:
            raise ValueError("cache cleanup candidate escaped isolated root")
        candidate.unlink()
        removed.append(str(candidate))
        removed_bytes += size
    return tuple(removed)


def stage_transaction(
    transaction: Mapping[str, Any],
    backend: IsolatedPacmanStaging,
    *,
    available_bytes: int | None = None,
    now=None,
) -> StagingResult:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.DISCOVERED.value:
        raise ValueError("only a DISCOVERED transaction may be staged")
    backend.prepare()
    packages = current["package_generation"]["packages"]
    requirement = sum(item["download_size"] for item in packages)
    requirement += max(64 * 1024 * 1024, requirement // 20)
    free = shutil.disk_usage(backend.cache).free if available_bytes is None else available_bytes
    manifest_path = _manifest_path(backend.cache, current["package_generation"]["id"])
    resumed = any(path.is_file() for path in backend.cache.iterdir() if ".pkg.tar." in path.name)
    if manifest_path.is_file():
        try:
            manifest = validate_manifest(json.loads(manifest_path.read_text()), current, backend.cache)
            staged = transition_transaction(current, UpdateState.STAGED, reason="exact staged payloads resumed", evidence={"manifest": str(manifest_path)}, now=now)
            return StagingResult(staged, manifest, requirement, free, True, ())
        except (OSError, ValueError, json.JSONDecodeError):
            resumed = True
    if free < requirement:
        blocked = transition_transaction(
            current, UpdateState.BLOCKED, blockers=["insufficient_staging_space"],
            evidence={"required": requirement, "available": free}, now=now,
        )
        return StagingResult(blocked, None, requirement, free, resumed, ())

    targets = _exact_targets(current)
    availability = backend.run(backend.availability_command(targets))
    available = _parse_availability(availability.stdout) if availability.returncode == 0 else {}
    missing = [
        item["name"] for item in packages
        if available.get(item["name"]) != (item["repository"], item["candidate_version"])
    ]
    extras = sorted(set(available) - {item["name"] for item in packages})
    if extras:
        blocked = transition_transaction(
            current, UpdateState.BLOCKED,
            blockers=[f"package_solver_drift:{name}" for name in extras],
            reason="dependency solver output differs from the discovered full transaction", now=now,
        )
        return StagingResult(blocked, None, requirement, free, resumed, ())
    if missing:
        blocked = transition_transaction(
            current, UpdateState.BLOCKED,
            blockers=[f"package_unavailable:{name}" for name in missing],
            reason="exact discovered package set is no longer available", now=now,
        )
        return StagingResult(blocked, None, requirement, free, resumed, ())

    downloaded = backend.run(backend.download_command(targets))
    if downloaded.returncode != 0:
        failed = transition_transaction(
            current, UpdateState.FAILED_RECOVERABLE,
            reason="isolated package download or Pacman signature verification failed",
            evidence={"exit_code": downloaded.returncode}, now=now,
        )
        return StagingResult(failed, None, requirement, free, resumed, ())

    expected = {(item["name"], item["candidate_version"]) for item in packages}
    package_by_name = {item["name"]: item for item in packages}
    payloads: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(backend.cache.iterdir(), key=lambda item: item.name):
        if not path.is_file() or path.is_symlink() or ".pkg.tar." not in path.name or path.name.endswith(".sig"):
            continue
        inspected = backend.run(backend.info_command(path))
        if inspected.returncode != 0:
            continue
        identity = _parse_file_info(inspected.stdout)
        if identity not in expected:
            continue
        if identity in seen:
            failed = transition_transaction(current, UpdateState.FAILED_RECOVERABLE, reason="duplicate exact package payloads are ambiguous", now=now)
            return StagingResult(failed, None, requirement, free, resumed, ())
        listed = backend.run(backend.list_command(path))
        if listed.returncode != 0:
            failed = transition_transaction(current, UpdateState.FAILED_RECOVERABLE, reason="exact package file inventory is unavailable", now=now)
            return StagingResult(failed, None, requirement, free, resumed, ())
        files = _parse_file_list(listed.stdout, identity[0])
        package = package_by_name[identity[0]]
        seen.add(identity)
        payloads.append({
            "name": identity[0], "version": identity[1], "path": str(path.resolve()),
            "sha256": _sha256(path), "size": path.stat().st_size,
            "signature_status": "verified-by-pacman",
            "provenance": repository_provenance(package["repository"]),
            "effects": classify_artifact(package_name=identity[0], roles=package["roles"], files=files),
        })
    if seen != expected:
        failed = transition_transaction(current, UpdateState.FAILED_RECOVERABLE, reason="staging completed without every exact payload", now=now)
        return StagingResult(failed, None, requirement, free, resumed, ())
    effect_summary = aggregate_effects(payloads)
    exact_current = dict(current)
    exact_current["activation"] = dict(current["activation"])
    exact_current["activation"]["requirements"] = list(effect_summary["activation_requirements"])
    exact_current["activation"]["required"] = bool(effect_summary["activation_requirements"])
    current = validate_transaction(exact_current)
    manifest = {
        "schema_version": 2,
        "transaction_id": current["transaction_id"],
        "package_generation_id": current["package_generation"]["id"],
        "payloads": sorted(payloads, key=lambda item: item["name"]),
        "verification": "pacman-signature-policy-sha256-and-file-effects",
        "effects": effect_summary,
    }
    validate_manifest(manifest, current, backend.cache)
    _write_manifest(manifest_path, manifest)
    keep = {Path(item["path"]).resolve() for item in payloads}
    keep.add(manifest_path.resolve())
    removed = cleanup_isolated_cache(backend.cache, keep)
    staged = transition_transaction(
        current, UpdateState.STAGED, reason="every exact payload is present and independently identified",
        evidence={"manifest": str(manifest_path), "payload_count": len(payloads)}, now=now,
    )
    return StagingResult(staged, manifest, requirement, free, resumed, removed)
