#!/usr/bin/env python3
"""Isolated Arch update discovery that never refreshes the live Pacman database."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
from typing import Any, Callable, Mapping, Sequence

from maho_update_effects import preliminary_boot_critical, repository_provenance
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
    selection_kind: str = "full"
    deferred_boot_packages: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class IsolatedPacmanDiscovery:
    """The only production command authority used by update discovery."""

    def __init__(
        self,
        isolated_root: str | os.PathLike[str],
        *,
        installed_db: str | os.PathLike[str] = LIVE_DB / "local",
        config_path: str | os.PathLike[str] = "/etc/pacman.conf",
        required_repositories: Sequence[str] | None = None,
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
        self.config = Path(config_path).resolve(strict=False)
        if not self.config.is_absolute():
            raise ValueError("Pacman config path must be absolute")
        self.required_repositories = tuple(required_repositories or ())
        if any(not isinstance(item, str) or not item for item in self.required_repositories):
            raise ValueError("required repository identity is invalid")
        self.runner = runner or self._system_run
        self.commands: list[tuple[str, ...]] = []

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

    def _prepare_download_dir(self, path: Path) -> None:
        path.mkdir(mode=0o755, parents=True, exist_ok=True)
        identity = self._download_identity()
        if identity is not None:
            os.chown(path, *identity)
            os.chmod(path, 0o755)

    def prepare(self) -> None:
        self.root.mkdir(mode=0o755, parents=True, exist_ok=True)
        self.db.mkdir(mode=0o755, parents=True, exist_ok=True)
        self._prepare_download_dir(self.db / "sync")
        self._prepare_download_dir(self.cache)
        destination = self.db / "local"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(self.installed_db, destination, symlinks=False)

    def sync_database_hashes(self) -> dict[str, str]:
        sync = self.db / "sync"
        observed: dict[str, str] = {}
        if sync.is_dir():
            for path in sorted(sync.glob("*.db")):
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError("isolated_repo_database_unsafe")
                import hashlib
                observed[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.required_repositories and set(observed) != set(self.required_repositories):
            raise RuntimeError(
                "isolated_repo_sync_mismatch: expected " + ",".join(self.required_repositories) +
                " observed " + ",".join(sorted(observed))
            )
        return observed

    @property
    def refresh_command(self) -> tuple[str, ...]:
        return (
            PACMAN, "--config", str(self.config), "--sync", "--refresh", "--dbpath", str(self.db),
            "--cachedir", str(self.cache), "--logfile", str(self.log), "--noconfirm",
        )

    @property
    def installed_command(self) -> tuple[str, ...]:
        return (PACMAN, "--config", str(self.config), "--query", "--dbpath", str(self.db))

    @property
    def transaction_command(self) -> tuple[str, ...]:
        return (
            PACMAN, "--config", str(self.config), "--sync", "--sysupgrade", "--print", "--print-format", "%r\t%n\t%v",
            "--dbpath", str(self.db),
        )

    def independent_transaction_command(self, excluded: Sequence[str]) -> tuple[str, ...]:
        names = tuple(sorted(set(excluded)))
        if not names or any(_PACKAGE.fullmatch(name) is None for name in names):
            raise ValueError("independent solver exclusion set is invalid")
        return (
            PACMAN, "--config", str(self.config), "--sync", "--sysupgrade", "--print", "--print-format", "%r\t%n\t%v",
            "--ignore", ",".join(names), "--dbpath", str(self.db),
        )

    def info_command(self, names: Sequence[str]) -> tuple[str, ...]:
        if not names or any(_PACKAGE.fullmatch(name) is None for name in names):
            raise ValueError("candidate package name is invalid")
        return (PACMAN, "--config", str(self.config), "--sync", "--info", "--dbpath", str(self.db), "--", *names)

    def _allowed(self, command: Sequence[str]) -> bool:
        argv = tuple(command)
        if argv in {self.refresh_command, self.installed_command, self.transaction_command}:
            return True
        independent_prefix = (
            PACMAN, "--config", str(self.config), "--sync", "--sysupgrade", "--print", "--print-format", "%r\t%n\t%v", "--ignore",
        )
        if argv[: len(independent_prefix)] == independent_prefix and len(argv) == len(independent_prefix) + 3:
            excluded, flag, db = argv[-3:]
            try:
                names = tuple(item for item in excluded.split(",") if item)
                return bool(names) and self.independent_transaction_command(names) == argv and flag == "--dbpath" and db == str(self.db)
            except ValueError:
                return False
        prefix = (PACMAN, "--config", str(self.config), "--sync", "--info", "--dbpath", str(self.db), "--")
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


def parse_name_versions(output: str, *, separator: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.strip().split(separator)
        if len(fields) != 2 or _PACKAGE.fullmatch(fields[0]) is None or not fields[1] or fields[0] in result:
            raise ValueError(f"ambiguous Pacman package identity output: {line!r}")
        result[fields[0]] = fields[1]
    return result


def parse_sync_info_records(output: str) -> dict[tuple[str, str, str], dict[str, Any]]:
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    current: dict[str, str] = {}
    for line in [*output.splitlines(), ""]:
        if not line.strip():
            if current:
                required = {"Name", "Version", "Repository", "Download Size", "Installed Size"}
                if not required.issubset(current):
                    raise ValueError("Pacman package metadata is incomplete")
                name = current["Name"]
                repository = current["Repository"]
                version = current["Version"]
                identity = (repository, name, version)
                if _PACKAGE.fullmatch(name) is None or _PACKAGE.fullmatch(repository) is None or identity in records:
                    raise ValueError("Pacman package metadata identity is ambiguous")
                records[identity] = {
                    "version": version,
                    "repository": repository,
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


def parse_sync_info(output: str) -> dict[str, dict[str, Any]]:
    by_identity = parse_sync_info_records(output)
    records: dict[str, dict[str, Any]] = {}
    for (_, name, _), info in by_identity.items():
        if name in records:
            raise ValueError("Pacman package metadata identity is ambiguous")
        records[name] = info
    return records


def parse_solver_plan(output: str) -> tuple[dict[str, str], dict[str, str]]:
    versions: dict[str, str] = {}
    repositories: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = line.strip().split("\t")
        if len(fields) != 3:
            raise ValueError(f"ambiguous Pacman solver output: {line!r}")
        repository, name, version = fields
        if (
            _PACKAGE.fullmatch(repository) is None
            or _PACKAGE.fullmatch(name) is None
            or not version
            or name in versions
        ):
            raise ValueError(f"ambiguous Pacman solver identity: {line!r}")
        versions[name] = version
        repositories[name] = repository
    return versions, repositories


# Recognize the host's Arch kernel and early-boot packages before asking Pacman
# for an independently executable normal generation. Exact staged inventories
# remain authoritative; this preliminary list is not an execution allowlist.
_ARCH_KERNEL_PACKAGES = frozenset({
    "linux", "linux-lts", "linux-zen", "linux-hardened", "linux-rt", "linux-rt-lts",
})
_ARCH_KERNEL_HEADERS = frozenset(f"{name}-headers" for name in _ARCH_KERNEL_PACKAGES)
# systemd-libs carries the shared libraries used by PID 1 and is version-locked
# to the systemd package; separating their generations breaks Pacman coherence.
_BOOT_SYSTEMD_PACKAGES = frozenset({
    "systemd", "systemd-libs", "systemd-boot", "systemd-sysvcompat", "systemd-ukify",
})


def package_roles(name: str) -> list[str]:
    roles: set[str] = set()
    if name in _ARCH_KERNEL_PACKAGES:
        roles.update({"kernel", "initramfs", "boot-artifacts"})
    if name in _ARCH_KERNEL_HEADERS:
        roles.update({"kernel-headers", "dkms"})
    if name in _BOOT_SYSTEMD_PACKAGES:
        roles.add("boot-policy")
    if name == "linux-firmware" or name.startswith("linux-firmware-"):
        roles.add("initramfs")
    if name in {"linux-cachyos", "linux-cachyos-lts"}:
        roles.update({"kernel", "initramfs", "boot-artifacts"})
        roles.add("primary-kernel" if name == "linux-cachyos" else "fallback-kernel")
    if name in {"linux-cachyos-headers", "linux-cachyos-lts-headers"}:
        roles.update({"kernel-headers", "dkms"})
        roles.add("primary-headers" if name == "linux-cachyos-headers" else "fallback-headers")
    lowered = name.lower()
    if name in {"intel-ucode", "amd-ucode"}:
        roles.update({"microcode", "initramfs", "boot-artifacts"})
    if name == "mkinitcpio":
        roles.add("initramfs")
    if name in {"limine", "systemd-boot"}:
        roles.add("bootloader")
    if "nvidia" in lowered and "dkms" in lowered:
        roles.update({"nvidia-kernel", "dkms", "initramfs"})
    elif "nvidia" in lowered and lowered.startswith("linux-"):
        roles.update({"nvidia-kernel", "initramfs"})
    elif "nvidia" in lowered:
        roles.add("nvidia-userspace")
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


def _candidate_rows(installed: Mapping[str, str], planned: Mapping[str, str]) -> list[tuple[str, str, str]]:
    return [
        (name, installed.get(name, "<not-installed>"), version)
        for name, version in sorted(planned.items())
        if installed.get(name) != version
    ]


def _packages_from_candidates(
    candidates: Sequence[tuple[str, str, str]],
    metadata: Mapping[tuple[str, str, str], Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    repositories: Mapping[str, str],
) -> tuple[list[dict[str, Any]], set[str]]:
    packages: list[dict[str, Any]] = []
    trusted_sources: set[str] = set()
    for name, installed, candidate in candidates:
        repository = repositories.get(name)
        if repository is None:
            raise ValueError(f"solver repository identity is unavailable: {name}")
        info = metadata.get((repository, name, candidate))
        if info is None:
            raise ValueError(f"candidate metadata does not bind exact solver identity: {repository}/{name}={candidate}")
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
    return packages, trusted_sources


def _provenance(packages: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {item["name"]: repository_provenance(str(item["repository"])) for item in packages}


def _version_set_digest(planned: Mapping[str, str]) -> str:
    import hashlib, json
    return hashlib.sha256(json.dumps(dict(sorted(planned.items())), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _solver_plan_digest(versions: Mapping[str, str], repositories: Mapping[str, str]) -> str:
    import hashlib, json
    payload = [
        {"name": name, "repository": repositories[name], "version": version}
        for name, version in sorted(versions.items())
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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
        raise RuntimeError(f"isolated_synchronization_failed: {refreshed.stderr.strip()}")
    backend.sync_database_hashes()
    installed_result = backend.run(backend.installed_command)
    if installed_result.returncode != 0:
        raise RuntimeError(f"installed package comparison failed: {installed_result.stderr.strip()}")
    installed = parse_name_versions(installed_result.stdout, separator=" ")
    planned_result = backend.run(backend.transaction_command)
    if planned_result.returncode != 0:
        detail = " | ".join(part for part in (planned_result.stderr.strip(), planned_result.stdout.strip()) if part)
        raise RuntimeError(f"package_solver_incoherent: {detail or 'Pacman solver returned nonzero'}")
    planned, planned_repositories = parse_solver_plan(planned_result.stdout)
    candidates = _candidate_rows(installed, planned)
    if not candidates:
        raise LookupError("no coherent update candidates were discovered")
    metadata_result = backend.run(backend.info_command([item[0] for item in candidates]))
    if metadata_result.returncode != 0:
        raise RuntimeError(f"candidate metadata lookup failed: {metadata_result.stderr.strip()}")
    metadata = parse_sync_info_records(metadata_result.stdout)
    evidence = security_evidence or {}
    packages, trusted_sources = _packages_from_candidates(candidates, metadata, evidence, planned_repositories)
    transaction = create_transaction(
        transaction_id=new_transaction_id(now=now, entropy=entropy),
        source_revision=source_revision,
        packages=packages,
        activation_requirements=activation_requirements(packages),
        recovery_generation_id=recovery_generation_id,
        provenance_by_package=_provenance(packages),
        selection={"kind": "full", "deferred_boot_packages": [], "solver_proof": {"kind": "full-system-solver", "versions_sha256": _version_set_digest(planned), "plan_sha256": _solver_plan_digest(planned, planned_repositories)}},
        now=now,
    )
    return DiscoveryResult(
        transaction=transaction,
        isolated_db=str(backend.db),
        candidate_count=len(packages),
        security_metadata_source=",".join(sorted(trusted_sources)) or None,
        selection_kind="full",
        deferred_boot_packages=(),
    )


def discover_independent_normal_updates(
    backend: IsolatedPacmanDiscovery,
    *,
    source_revision: str,
    security_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    recovery_generation_id: str | None = None,
    now: datetime | None = None,
    entropy: str | None = None,
) -> DiscoveryResult:
    """Ask an isolated Pacman solver for a coherent generation that defers preliminary boot effects.

    The exclusion is discovery-only. The resulting exact generation is later staged and
    installed from local artifacts; no production Pacman execution uses --ignore.
    """
    backend.prepare()
    refreshed = backend.run(backend.refresh_command)
    if refreshed.returncode != 0:
        raise RuntimeError(f"isolated_synchronization_failed: {refreshed.stderr.strip()}")
    backend.sync_database_hashes()
    installed_result = backend.run(backend.installed_command)
    if installed_result.returncode != 0:
        raise RuntimeError(f"installed package comparison failed: {installed_result.stderr.strip()}")
    installed = parse_name_versions(installed_result.stdout, separator=" ")
    full_result = backend.run(backend.transaction_command)
    if full_result.returncode != 0:
        detail = " | ".join(part for part in (full_result.stderr.strip(), full_result.stdout.strip()) if part)
        raise RuntimeError(f"package_solver_incoherent: {detail or 'Pacman solver returned nonzero'}")
    full_planned, full_repositories = parse_solver_plan(full_result.stdout)
    full_candidates = _candidate_rows(installed, full_planned)
    if not full_candidates:
        raise LookupError("no coherent update candidates were discovered")
    metadata_result = backend.run(backend.info_command([item[0] for item in full_candidates]))
    if metadata_result.returncode != 0:
        raise RuntimeError(f"candidate metadata lookup failed: {metadata_result.stderr.strip()}")
    metadata = parse_sync_info_records(metadata_result.stdout)
    evidence = security_evidence or {}
    full_packages, _ = _packages_from_candidates(full_candidates, metadata, evidence, full_repositories)
    deferred = sorted(item["name"] for item in full_packages if preliminary_boot_critical(item["roles"]))
    if deferred:
        normal_result = backend.run(backend.independent_transaction_command(deferred))
        if normal_result.returncode != 0:
            detail = " | ".join(part for part in (normal_result.stderr.strip(), normal_result.stdout.strip()) if part)
            raise RuntimeError(f"independent_non_boot_solver_incoherent: {detail or 'Pacman solver returned nonzero'}")
        selected_planned, selected_repositories = parse_solver_plan(normal_result.stdout)
    else:
        selected_planned = full_planned
        selected_repositories = full_repositories
    selected_candidates = _candidate_rows(installed, selected_planned)
    if not selected_candidates:
        raise LookupError("no coherent non-boot update candidates were discovered")
    for name, _, version in selected_candidates:
        if full_planned.get(name) != version:
            raise RuntimeError(f"independent_non_boot_solver_version_drift:{name}")
        if full_repositories.get(name) != selected_repositories.get(name):
            raise RuntimeError(f"independent_non_boot_solver_repository_drift:{name}")
    packages, trusted_sources = _packages_from_candidates(selected_candidates, metadata, evidence, selected_repositories)
    escaped = sorted(item["name"] for item in packages if preliminary_boot_critical(item["roles"]))
    if escaped:
        raise RuntimeError("independent_non_boot_solver_consumed_boot_effect:" + ",".join(escaped))
    kind = "independent-normal" if deferred else "full"
    proof = {
        "kind": "isolated-pacman-independent-generation" if deferred else "full-system-solver",
        "deferred_boot_packages": deferred,
        "full_versions_sha256": _version_set_digest(full_planned),
        "selected_versions_sha256": _version_set_digest(selected_planned),
        "full_plan_sha256": _solver_plan_digest(full_planned, full_repositories),
        "selected_plan_sha256": _solver_plan_digest(selected_planned, selected_repositories),
        "selected_versions_match_full": True,
        "selected_repositories_match_full": True,
        "production_ignore_execution": False,
    }
    transaction = create_transaction(
        transaction_id=new_transaction_id(now=now, entropy=entropy),
        source_revision=source_revision,
        packages=packages,
        activation_requirements=activation_requirements(packages),
        recovery_generation_id=recovery_generation_id,
        provenance_by_package=_provenance(packages),
        selection={"kind": kind, "deferred_boot_packages": deferred, "solver_proof": proof},
        now=now,
    )
    return DiscoveryResult(
        transaction=transaction,
        isolated_db=str(backend.db),
        candidate_count=len(packages),
        security_metadata_source=",".join(sorted(trusted_sources)) or None,
        selection_kind=kind,
        deferred_boot_packages=tuple(deferred),
    )


def discover_coherent_subset_updates(
    backend: IsolatedPacmanDiscovery,
    *,
    target_packages: Sequence[str],
    source_revision: str,
    security_evidence: Mapping[str, Mapping[str, Any]] | None = None,
    recovery_generation_id: str | None = None,
    now: datetime | None = None,
    entropy: str | None = None,
) -> DiscoveryResult:
    """Prove an exact requested subset is a coherent independent Pacman transaction.

    The full current solver result is established first. Every other update candidate
    is then deferred only inside the isolated solver. The subset is accepted only if
    Pacman still solves it, selects exactly the requested targets, and preserves the
    exact versions chosen by the full-system solver.
    """
    targets = tuple(sorted(set(str(item) for item in target_packages)))
    if not targets or any(_PACKAGE.fullmatch(item) is None for item in targets):
        raise ValueError("coherent subset target package set is invalid")
    backend.prepare()
    refreshed = backend.run(backend.refresh_command)
    if refreshed.returncode != 0:
        raise RuntimeError(f"isolated_synchronization_failed: {refreshed.stderr.strip()}")
    backend.sync_database_hashes()
    installed_result = backend.run(backend.installed_command)
    if installed_result.returncode != 0:
        raise RuntimeError(f"installed package comparison failed: {installed_result.stderr.strip()}")
    installed = parse_name_versions(installed_result.stdout, separator=" ")
    full_result = backend.run(backend.transaction_command)
    if full_result.returncode != 0:
        detail = " | ".join(part for part in (full_result.stderr.strip(), full_result.stdout.strip()) if part)
        raise RuntimeError(f"package_solver_incoherent: {detail or 'Pacman solver returned nonzero'}")
    full_planned, full_repositories = parse_solver_plan(full_result.stdout)
    full_candidates = _candidate_rows(installed, full_planned)
    if not full_candidates:
        raise LookupError("no coherent update candidates were discovered")
    full_names = {name for name, _, _ in full_candidates}
    missing = sorted(set(targets) - full_names)
    if missing:
        raise LookupError("requested coherent subset is not currently updateable:" + ",".join(missing))
    metadata_result = backend.run(backend.info_command([item[0] for item in full_candidates]))
    if metadata_result.returncode != 0:
        raise RuntimeError(f"candidate metadata lookup failed: {metadata_result.stderr.strip()}")
    metadata = parse_sync_info_records(metadata_result.stdout)
    evidence = security_evidence or {}
    full_packages, _ = _packages_from_candidates(full_candidates, metadata, evidence, full_repositories)
    target_rows = {item["name"]: item for item in full_packages if item["name"] in targets}
    pre_boot = sorted(name for name, item in target_rows.items() if preliminary_boot_critical(item["roles"]))
    if pre_boot:
        raise ValueError("coherent subset target is preliminarily boot-critical:" + ",".join(pre_boot))
    deferred = sorted(full_names - set(targets))
    if deferred:
        subset_result = backend.run(backend.independent_transaction_command(deferred))
        if subset_result.returncode != 0:
            detail = " | ".join(part for part in (subset_result.stderr.strip(), subset_result.stdout.strip()) if part)
            raise RuntimeError(f"coherent_subset_solver_incoherent: {detail or 'Pacman solver returned nonzero'}")
        selected_planned, selected_repositories = parse_solver_plan(subset_result.stdout)
    else:
        selected_planned = full_planned
        selected_repositories = full_repositories
    selected_candidates = _candidate_rows(installed, selected_planned)
    selected_names = {name for name, _, _ in selected_candidates}
    if selected_names != set(targets):
        raise RuntimeError(
            "coherent_subset_solver_selected_unexpected_packages: expected " + ",".join(targets) +
            " observed " + ",".join(sorted(selected_names))
        )
    for name, _, version in selected_candidates:
        if full_planned.get(name) != version:
            raise RuntimeError(f"coherent_subset_solver_version_drift:{name}")
        if full_repositories.get(name) != selected_repositories.get(name):
            raise RuntimeError(f"coherent_subset_solver_repository_drift:{name}")
    packages, trusted_sources = _packages_from_candidates(selected_candidates, metadata, evidence, selected_repositories)
    proof = {
        "kind": "isolated-pacman-coherent-subset",
        "target_packages": list(targets),
        "deferred_packages": deferred,
        "full_versions_sha256": _version_set_digest(full_planned),
        "selected_versions_sha256": _version_set_digest(selected_planned),
        "full_plan_sha256": _solver_plan_digest(full_planned, full_repositories),
        "selected_plan_sha256": _solver_plan_digest(selected_planned, selected_repositories),
        "selected_versions_match_full": True,
        "selected_repositories_match_full": True,
        "production_ignore_execution": False,
    }
    transaction = create_transaction(
        transaction_id=new_transaction_id(now=now, entropy=entropy),
        source_revision=source_revision,
        packages=packages,
        activation_requirements=activation_requirements(packages),
        recovery_generation_id=recovery_generation_id,
        provenance_by_package=_provenance(packages),
        selection={"kind": "coherent-subset", "deferred_boot_packages": [], "solver_proof": proof},
        now=now,
    )
    return DiscoveryResult(
        transaction=transaction,
        isolated_db=str(backend.db),
        candidate_count=len(packages),
        security_metadata_source=",".join(sorted(trusted_sources)) or None,
        selection_kind="coherent-subset",
        deferred_boot_packages=(),
    )
