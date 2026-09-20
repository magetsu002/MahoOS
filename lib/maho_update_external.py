#!/usr/bin/env python3
"""AUR artifact-set handoff into Maho Update without granting install authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from maho_update_discovery import package_roles
from maho_update_effects import aggregate_effects, classify_artifact, validate_provenance
from maho_update_staging import validate_manifest
from maho_update_state import UpdateState, create_transaction, new_transaction_id, transition_transaction, validate_transaction

LIVE_CACHE = Path("/var/cache/pacman/pkg")


@dataclass(frozen=True)
class ExternalStagingResult:
    transaction: dict[str, Any]
    manifest: dict[str, Any]
    routing_target: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(receipt)
    if data.get("version") != 2 or data.get("kind") != "aur-isolated-build":
        raise ValueError("AUR artifact receipt schema is invalid")
    if data.get("status") != "verified" or data.get("phase") != "complete":
        raise ValueError("AUR artifact receipt is not verified complete")
    if data.get("automatic_install") is not False or data.get("installation_authority") != "maho-update-only":
        raise ValueError("AUR artifact receipt claims invalid installation authority")
    authority = data.get("repository_authority")
    if not isinstance(authority, Mapping):
        raise ValueError("AUR artifact receipt has no repository authority")
    authority_config = authority.get("config")
    authority_sha = authority.get("sha256")
    if (
        not isinstance(authority_config, str)
        or not authority_config.startswith("/")
        or not isinstance(authority_sha, str)
        or len(authority_sha) != 64
        or any(ch not in "0123456789abcdef" for ch in authority_sha)
    ):
        raise ValueError("AUR artifact repository authority is invalid")
    packages = data.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("AUR artifact receipt has no accepted artifacts")
    seen: set[str] = set()
    for raw in packages:
        if not isinstance(raw, Mapping):
            raise ValueError("AUR artifact entry is invalid")
        name = raw.get("name")
        installed = raw.get("installed_version")
        version = raw.get("version")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("AUR artifact package identity is invalid")
        if not isinstance(installed, str) or not installed or not isinstance(version, str) or not version or installed == version:
            raise ValueError("AUR artifact version transition is invalid")
        if not isinstance(raw.get("sha256"), str) or len(raw["sha256"]) != 64:
            raise ValueError("AUR artifact digest is invalid")
        provenance = validate_provenance(raw.get("provenance", {}))
        if provenance["kind"] != "aur-built":
            raise ValueError("external artifact provenance is not AUR-built")
        effects = raw.get("effects")
        if not isinstance(effects, Mapping) or effects.get("classification") not in {"normal", "boot-critical"}:
            raise ValueError("AUR artifact effect evidence is invalid")
        seen.add(name)
    return data


def transaction_from_aur_receipt(
    receipt: Mapping[str, Any],
    *,
    source_revision: str,
    now=None,
    entropy: str | None = None,
) -> dict[str, Any]:
    data = _validate_receipt(receipt)
    packages: list[dict[str, Any]] = []
    provenance: dict[str, Mapping[str, Any]] = {}
    for artifact in data["packages"]:
        name = str(artifact["name"])
        packages.append({
            "name": name,
            "installed_version": str(artifact["installed_version"]),
            "candidate_version": str(artifact["version"]),
            "repository": "aur",
            "download_size": int(artifact.get("size", 0)),
            "installed_size": 0,
            "security_relevant": False,
            "roles": package_roles(name),
        })
        provenance[name] = validate_provenance(artifact["provenance"])
    effects = aggregate_effects(data["packages"])
    artifact_ids = sorted(str(item.get("artifact_id", "")) for item in data["packages"])
    if any(not value.startswith("aurpkg-") for value in artifact_ids):
        raise ValueError("AUR artifact Maho identity is missing")
    return create_transaction(
        transaction_id=new_transaction_id(now=now, entropy=entropy),
        source_revision=source_revision,
        packages=packages,
        activation_requirements=effects["activation_requirements"],
        recovery_generation_id=None,
        provenance_by_package=provenance,
        selection={
            "kind": "artifact-set",
            "deferred_boot_packages": [],
            "solver_proof": {
                "kind": "aur-artifact-production",
                "dependencies_proven": False,
                "artifact_ids": artifact_ids,
                "repository_authority": data.get("repository_authority"),
            },
        },
        now=now,
    )


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(command), text=True, capture_output=True, check=False, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})


def _json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _dependency_solver_proof(
    receipt: Mapping[str, Any],
    *,
    pacman: str,
    pacman_config: str | Path,
) -> dict[str, Any]:
    data = _validate_receipt(receipt)
    config = Path(pacman_config)
    if config.is_symlink() or not config.is_file():
        raise ValueError("AUR dependency solver Pacman authority is unavailable")
    config = config.resolve(strict=True)
    authority = data.get("repository_authority")
    if not isinstance(authority, Mapping):
        raise ValueError("AUR receipt repository authority is missing")
    if str(authority.get("config") or "") != str(config):
        raise ValueError("AUR dependency solver repository authority path drifted")
    expected_config_sha = str(authority.get("sha256") or "")
    if len(expected_config_sha) != 64 or _sha256(config) != expected_config_sha:
        raise ValueError("AUR dependency solver repository authority digest drifted")

    artifacts = sorted(data["packages"], key=lambda item: str(item["name"]))
    exact_paths: list[str] = []
    expected_local: dict[str, tuple[str, str]] = {}
    for artifact in artifacts:
        source = Path(str(artifact.get("path", "")))
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"AUR dependency solver artifact path is unsafe:{artifact['name']}")
        resolved = source.resolve(strict=True)
        if _sha256(resolved) != artifact["sha256"]:
            raise ValueError(f"AUR dependency solver artifact changed after build:{artifact['name']}")
        name = str(artifact["name"])
        version = str(artifact["version"])
        expected_local[name] = (version, str(resolved))
        exact_paths.append(str(resolved))

    result = _run((
        pacman, "--config", str(config), "--upgrade", "--print",
        "--print-format", "%r\t%n\t%v\t%l", "--", *exact_paths,
    ))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise ValueError(f"AUR dependency solver failed:{detail or result.returncode}")

    local_rows: dict[str, dict[str, str]] = {}
    repository_rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in result.stdout.splitlines():
        if not raw.strip():
            continue
        fields = raw.split("\t")
        if len(fields) != 4:
            raise ValueError("AUR dependency solver output is ambiguous")
        repository, name, version, location = (field.strip() for field in fields)
        if not name or not version or name in seen:
            raise ValueError("AUR dependency solver package identity is ambiguous")
        seen.add(name)
        if repository == "local":
            expected = expected_local.get(name)
            try:
                observed_path = str(Path(location).resolve(strict=True))
            except OSError as exc:
                raise ValueError(f"AUR dependency solver local artifact is unavailable:{name}") from exc
            if expected is None or expected != (version, observed_path):
                raise ValueError(f"AUR dependency solver local artifact drifted:{name}")
            local_rows[name] = {
                "repository": "local",
                "name": name,
                "version": version,
                "path": observed_path,
            }
            continue
        if not repository or repository == "local" or not location:
            raise ValueError("AUR dependency solver repository row is invalid")
        repository_rows.append({
            "repository": repository,
            "name": name,
            "version": version,
            "location": location,
        })

    if set(local_rows) != set(expected_local):
        raise ValueError("AUR dependency solver did not preserve the exact local artifact set")

    material = {
        "local_artifacts": [local_rows[name] for name in sorted(local_rows)],
        "repository_dependency_changes": sorted(
            repository_rows,
            key=lambda item: (item["repository"], item["name"], item["version"]),
        ),
        "repository_authority": {
            "config": str(config),
            "sha256": expected_config_sha,
        },
    }
    return {
        "kind": "aur-artifact-dependency-closure",
        "dependencies_proven": True,
        "artifact_ids": sorted(str(item["artifact_id"]) for item in artifacts),
        "local_artifacts": material["local_artifacts"],
        "repository_dependency_changes": material["repository_dependency_changes"],
        "repository_authority": material["repository_authority"],
        "normal_profile_compatible": not repository_rows,
        "proof_sha256": _json_digest(material),
    }


def _parse_info(output: str) -> tuple[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() in {"Name", "Version"}:
            fields[key.strip()] = value.strip()
    name, version = fields.get("Name", ""), fields.get("Version", "")
    if not name or not version:
        raise ValueError("external package identity is unavailable")
    return name, version


def _parse_list(output: str, name: str) -> list[str]:
    files: list[str] = []
    for raw in output.splitlines():
        if not raw.strip():
            continue
        observed, sep, path = raw.strip().partition(" ")
        if sep != " " or observed != name or not path.startswith("/"):
            raise ValueError("external package file inventory is ambiguous")
        files.append(path)
    if not files:
        raise ValueError("external package file inventory is empty")
    return files


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
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


def stage_aur_artifacts(
    transaction: Mapping[str, Any],
    receipt: Mapping[str, Any],
    cache_root: str | Path,
    *,
    pacman: str = "/usr/bin/pacman",
    pacman_config: str | Path | None = None,
    now=None,
) -> ExternalStagingResult:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.DISCOVERED.value:
        raise ValueError("AUR artifact staging requires DISCOVERED transaction")
    if current["selection"]["kind"] != "artifact-set":
        raise ValueError("AUR artifact staging requires artifact-set selection")
    data = _validate_receipt(receipt)
    authority = data["repository_authority"]
    config = Path(pacman_config if pacman_config is not None else str(authority["config"]))
    dependency_proof = _dependency_solver_proof(
        data,
        pacman=pacman,
        pacman_config=config,
    )
    updated = dict(current)
    updated["selection"] = {
        "kind": "artifact-set",
        "deferred_boot_packages": [],
        "solver_proof": dependency_proof,
    }
    current = validate_transaction(updated)
    cache = Path(cache_root)
    if not cache.is_absolute():
        raise ValueError("external artifact staging cache must be absolute")
    cache = cache.resolve(strict=False)
    live = LIVE_CACHE.resolve(strict=False)
    if cache == live or live in cache.parents or cache in live.parents:
        raise ValueError("external artifact staging cache overlaps live Pacman cache")
    cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(cache, 0o700)

    expected = {item["name"]: item for item in current["package_generation"]["packages"]}
    tx_provenance: dict[str, dict[str, Any]] = {}
    for raw in current["source_provenance"]["packages"]:
        entry = dict(raw)
        name = str(entry.pop("name"))
        tx_provenance[name] = validate_provenance(entry)
    observed: set[str] = set()
    payloads: list[dict[str, Any]] = []
    for artifact in data["packages"]:
        name = str(artifact["name"])
        package = expected.get(name)
        if package is None or name in observed or package["candidate_version"] != artifact["version"]:
            raise ValueError("AUR artifact set does not match exact package generation")
        if package["installed_version"] != artifact["installed_version"]:
            raise ValueError("AUR artifact installed-version basis drifted")
        provenance = validate_provenance(artifact["provenance"])
        if tx_provenance.get(name) != provenance:
            raise ValueError(f"AUR artifact provenance drifted:{name}")
        source = Path(str(artifact.get("path", "")))
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"AUR artifact source path is unsafe:{name}")
        if _sha256(source) != artifact["sha256"] or source.stat().st_size != artifact.get("size"):
            raise ValueError(f"AUR artifact payload changed after build:{name}")
        destination = cache / f"{artifact['artifact_id']}-{source.name}"
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file() or _sha256(destination) != artifact["sha256"]:
                raise ValueError(f"external staging collision:{name}")
        else:
            temporary = cache / f".{destination.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
            shutil.copyfile(source, temporary, follow_symlinks=False)
            os.chmod(temporary, 0o600)
            if _sha256(temporary) != artifact["sha256"]:
                temporary.unlink(missing_ok=True)
                raise ValueError(f"external artifact copy verification failed:{name}")
            os.replace(temporary, destination)
        info = _run((pacman, "--query", "--file", "--info", "--", str(destination)))
        if info.returncode != 0 or _parse_info(info.stdout) != (name, artifact["version"]):
            raise ValueError(f"external staged package identity drifted:{name}")
        listing = _run((pacman, "--query", "--file", "--list", "--", str(destination)))
        if listing.returncode != 0:
            raise ValueError(f"external staged package inventory unavailable:{name}")
        exact_effects = classify_artifact(package_name=name, roles=package["roles"], files=_parse_list(listing.stdout, name))
        if dict(artifact["effects"]) != exact_effects:
            raise ValueError(f"external artifact effect evidence drifted:{name}")
        payloads.append({
            "name": name,
            "version": artifact["version"],
            "path": str(destination),
            "sha256": artifact["sha256"],
            "size": artifact["size"],
            "signature_status": "maho-isolated-build",
            "provenance": provenance,
            "effects": exact_effects,
            "artifact_id": artifact["artifact_id"],
        })
        observed.add(name)
    if observed != set(expected):
        raise ValueError("AUR artifact staging set is incomplete")

    effects = aggregate_effects(payloads)
    updated = dict(current)
    updated["activation"] = dict(current["activation"])
    updated["activation"]["requirements"] = list(effects["activation_requirements"])
    updated["activation"]["required"] = bool(effects["activation_requirements"])
    current = validate_transaction(updated)
    manifest = {
        "schema_version": 2,
        "transaction_id": current["transaction_id"],
        "package_generation_id": current["package_generation"]["id"],
        "payloads": sorted(payloads, key=lambda item: item["name"]),
        "verification": "maho-aur-artifact-reverified",
        "effects": effects,
    }
    validate_manifest(manifest, current, cache)
    _write_manifest(cache / f"manifest-{current['package_generation']['id']}.json", manifest)
    staged = transition_transaction(
        current,
        UpdateState.STAGED,
        reason="AUR artifacts copied into Maho staging and reverified from exact package contents",
        evidence={
            "artifact_ids": sorted(item["artifact_id"] for item in payloads),
            "effects": effects,
            "dependency_coherence": "proven",
            "dependency_proof_sha256": dependency_proof["proof_sha256"],
            "repository_dependency_changes": dependency_proof["repository_dependency_changes"],
            "normal_profile_compatible": dependency_proof["normal_profile_compatible"],
        },
        now=now,
    )
    route = "m4b" if effects["classification"] == "boot-critical" else "normal"
    return ExternalStagingResult(staged, manifest, route)
