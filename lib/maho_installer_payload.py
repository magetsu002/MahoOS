#!/usr/bin/env python3
"""Exact, closed payload authority for MahoOS target assembly."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePath
import re
import subprocess
from typing import Any, Mapping, Sequence


_SHA40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_PACKAGE_SUFFIXES = (".pkg.tar.zst", ".pkg.tar.xz", ".pkg.tar.gz")
REQUIRED_PACKAGES = {
    "base", "btrfs-progs", "cryptsetup", "dosfstools", "limine", "mkinitcpio",
    "networkmanager", "nftables", "openssl", "sbsigntools", "sddm", "snapper", "sudo", "maho-os",
    "linux-cachyos", "linux-cachyos-headers",
    "linux-cachyos-lts", "linux-cachyos-lts-headers",
}
MICROCODE_PACKAGES = {"amd-ucode", "intel-ucode"}
UNSIGNED_UPSTREAM_REPOSITORIES = {"core", "extra", "multilib"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def _archive_member(package: Path, member: str, *, run=_run) -> bytes:
    result = run(("bsdtar", "-xOf", str(package), member))
    if result.returncode != 0:
        raise ValueError(f"package member is unavailable: {package.name}:{member}")
    return result.stdout.encode()


def _package_info(package: Path, *, run=_run) -> dict[str, Any]:
    result = run(("bsdtar", "-xOf", str(package), ".PKGINFO"))
    if result.returncode != 0:
        raise ValueError(f"package metadata is unavailable: {package.name}")
    values: dict[str, Any] = {"depends": [], "provides": []}
    for line in result.stdout.splitlines():
        if " = " not in line:
            continue
        key, value = line.split(" = ", 1)
        if key in {"pkgname", "pkgver", "arch"}:
            values[key] = value
        elif key == "depend":
            values["depends"].append(value)
        elif key == "provides":
            values["provides"].append(value)
    if not {"pkgname", "pkgver", "arch"}.issubset(values):
        raise ValueError(f"package metadata is incomplete: {package.name}")
    values["depends"] = sorted(set(values["depends"]))
    values["provides"] = sorted(set(values["provides"]))
    return values


def _dependency_atom(value: str) -> str:
    atom = re.split(r"[<>=]", value, maxsplit=1)[0].strip()
    if not atom or not re.fullmatch(r"[A-Za-z0-9@._+:-]+", atom):
        raise ValueError(f"package dependency identity is invalid: {value}")
    return atom


def _validate_dependency_closure(packages: Sequence[Mapping[str, Any]]) -> None:
    provided: set[str] = set()
    for item in packages:
        provided.add(_dependency_atom(str(item["name"])))
        for value in item.get("provides", []):
            provided.add(_dependency_atom(str(value)))
    missing = sorted({
        _dependency_atom(str(value))
        for item in packages
        for value in item.get("depends", [])
        if _dependency_atom(str(value)) not in provided
    })
    if missing:
        raise ValueError(f"installer payload dependency closure is incomplete: {missing}")


def _repository_records(repositories: Mapping[str, Path], *, run=_run) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name, path in sorted(repositories.items()):
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", name) or not path.is_file():
            raise ValueError("repository database identity is invalid")
        database_sha256 = _sha256_file(path)
        signature = path.with_name(path.name + ".sig")
        if signature.is_file():
            result = run(("pacman-key", "--verify", str(signature), str(path)))
            if result.returncode != 0:
                raise ValueError(f"repository database signature verification failed: {name}")
            signature_status = "verified-detached"
            signature_file: str | None = signature.name
            signature_sha256: str | None = _sha256_file(signature)
            # Successful verification is the boolean gate; the exact detached
            # signature bytes are the deterministic evidence identity.
            evidence = signature.read_bytes()
        else:
            if name not in UNSIGNED_UPSTREAM_REPOSITORIES:
                raise ValueError(f"repository database signature is missing: {name}")
            # Arch's official repository databases are unsigned upstream. They
            # are solver/acquisition provenance only; exact package archives
            # and their detached signatures remain the payload authority.
            signature_status = "upstream-unsigned-non-authoritative"
            signature_file = None
            signature_sha256 = None
            evidence = _canonical({
                "status": signature_status,
                "name": name,
                "database_sha256": database_sha256,
            })
        records.append({
            "name": name,
            "database_file": path.name,
            "database_sha256": database_sha256,
            "signature_status": signature_status,
            "signature_file": signature_file,
            "signature_sha256": signature_sha256,
            "verification_evidence_sha256": hashlib.sha256(evidence).hexdigest(),
            "authoritative_for_payload": False,
        })
    if not records:
        raise ValueError("at least one repository database identity is required")
    return records


def build_payload_manifest(
    package_dir: Path, *, source_revision: str, repositories: Mapping[str, Path], run=_run,
) -> dict[str, Any]:
    """Verify a fully downloaded package set and return its immutable authority."""
    if _SHA40.fullmatch(source_revision) is None:
        raise ValueError("payload source revision is invalid")
    packages: list[dict[str, Any]] = []
    seen: set[str] = set()
    maho_version = ""
    runtime_archive_sha256 = ""
    for package in sorted(path for path in package_dir.iterdir() if path.name.endswith(_PACKAGE_SUFFIXES)):
        info = _package_info(package, run=run)
        name = info["pkgname"]
        if name in seen:
            raise ValueError(f"payload contains duplicate package name: {name}")
        seen.add(name)
        digest = _sha256_file(package)
        if name == "maho-os":
            release = json.loads(_archive_member(package, "usr/lib/maho/share/maho/release.json", run=run))
            if not isinstance(release, Mapping) or release.get("source_revision") != source_revision:
                raise ValueError("Maho package source revision does not match the payload")
            verification = {
                "status": "exact-local-build",
                "evidence_sha256": hashlib.sha256(_canonical(release)).hexdigest(),
            }
            maho_version = info["pkgver"]
            runtime_archive_sha256 = digest
            repository = "maho-exact-build"
        else:
            signature = package.with_name(package.name + ".sig")
            if not signature.is_file():
                raise ValueError(f"detached package signature is missing: {package.name}")
            result = run(("pacman-key", "--verify", str(signature), str(package)))
            if result.returncode != 0:
                raise ValueError(f"package signature verification failed: {package.name}")
            verification = {
                "status": "verified",
                # Bind the exact detached signature, not verifier console
                # wording, locale, or warning text.
                "evidence_sha256": _sha256_file(signature),
            }
            repository = "signed-pacman-repository"
        packages.append({
            "name": name,
            "version": info["pkgver"],
            "architecture": info["arch"],
            "filename": package.name,
            "sha256": digest,
            "repository": repository,
            "signature": verification,
            "depends": list(info["depends"]),
            "provides": list(info["provides"]),
        })
    _validate_dependency_closure(packages)
    material = {
        "schema_version": 2,
        "kind": "maho-installer-payload",
        "metadata_authority": "verified-package-archives",
        "source_revision": source_revision,
        "package_version": maho_version,
        "runtime_archive_sha256": runtime_archive_sha256,
        "repositories": _repository_records(repositories, run=run),
        "packages": packages,
    }
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    payload = material | {
        "payload_sha256": digest,
        "package_generation_id": f"pkg-{digest}",
    }
    return validate_payload_manifest(payload, package_dir=package_dir)


def validate_payload_manifest(
    payload: Mapping[str, Any], *, package_dir: Path | None = None,
) -> dict[str, Any]:
    fields = {
        "schema_version", "kind", "metadata_authority", "source_revision", "package_version",
        "runtime_archive_sha256", "repositories", "packages", "payload_sha256",
        "package_generation_id",
    }
    if not isinstance(payload, Mapping) or set(payload) != fields:
        raise ValueError("installer payload fields are invalid")
    if payload.get("schema_version") != 2 or payload.get("kind") != "maho-installer-payload":
        raise ValueError("installer payload schema is unsupported")
    if payload.get("metadata_authority") != "verified-package-archives":
        raise ValueError("installer payload metadata authority is invalid")
    if _SHA40.fullmatch(str(payload.get("source_revision", ""))) is None:
        raise ValueError("payload source revision is invalid")
    if not payload.get("package_version") or _SHA256.fullmatch(str(payload.get("runtime_archive_sha256", ""))) is None:
        raise ValueError("Maho package identity is invalid")
    repositories = payload.get("repositories")
    packages = payload.get("packages")
    if not isinstance(repositories, list) or not repositories or not isinstance(packages, list) or not packages:
        raise ValueError("payload repository/package inventory is incomplete")
    if packages != sorted(packages, key=lambda item: str(item.get("filename", ""))):
        raise ValueError("payload package inventory is not canonical")
    repository_names: set[str] = set()
    for item in repositories:
        required = {
            "name", "database_file", "database_sha256", "signature_status",
            "signature_file", "signature_sha256", "verification_evidence_sha256",
            "authoritative_for_payload",
        }
        if not isinstance(item, Mapping) or set(item) != required:
            raise ValueError("payload repository record is invalid")
        name = str(item["name"])
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", name) or name in repository_names:
            raise ValueError("payload repository identity is invalid")
        repository_names.add(name)
        if _SHA256.fullmatch(str(item["database_sha256"])) is None or _SHA256.fullmatch(str(item["verification_evidence_sha256"])) is None:
            raise ValueError("payload repository digest is invalid")
        database_file = str(item["database_file"])
        if PurePath(database_file).name != database_file:
            raise ValueError("payload repository filename is invalid")
        if item.get("authoritative_for_payload") is not False:
            raise ValueError("repository database must not become payload authority")
        status = item.get("signature_status")
        if status == "verified-detached":
            signature_file = item.get("signature_file")
            if (
                not isinstance(signature_file, str)
                or PurePath(signature_file).name != signature_file
                or _SHA256.fullmatch(str(item.get("signature_sha256", ""))) is None
            ):
                raise ValueError("signed repository database evidence is invalid")
        elif status == "upstream-unsigned-non-authoritative":
            if name not in UNSIGNED_UPSTREAM_REPOSITORIES or item.get("signature_file") is not None or item.get("signature_sha256") is not None:
                raise ValueError("unsigned repository database provenance is invalid")
        else:
            raise ValueError("repository database signature status is invalid")
    if repositories != sorted(repositories, key=lambda item: str(item["name"])):
        raise ValueError("payload repository inventory is not canonical")
    names: set[str] = set()
    for item in packages:
        required = {"name", "version", "architecture", "filename", "sha256", "repository", "signature", "depends", "provides"}
        if not isinstance(item, Mapping) or set(item) != required:
            raise ValueError("payload package record is invalid")
        name = str(item["name"])
        filename = str(item["filename"])
        if not name or name in names or PurePath(filename).name != filename:
            raise ValueError("payload package identity is invalid")
        names.add(name)
        if _SHA256.fullmatch(str(item["sha256"])) is None:
            raise ValueError("payload package digest is invalid")
        for field in ("depends", "provides"):
            values = item[field]
            if (
                not isinstance(values, list)
                or values != sorted(set(values))
                or any(not isinstance(value, str) or not value for value in values)
            ):
                raise ValueError(f"payload package {field} inventory is invalid")
            for value in values:
                _dependency_atom(value)
        signature = item["signature"]
        if not isinstance(signature, Mapping) or set(signature) != {"status", "evidence_sha256"}:
            raise ValueError("payload signature evidence is invalid")
        allowed = {"exact-local-build"} if name == "maho-os" else {"verified"}
        if signature.get("status") not in allowed or _SHA256.fullmatch(str(signature.get("evidence_sha256", ""))) is None:
            raise ValueError("payload package is not verified")
        if package_dir is not None:
            path = package_dir / filename
            if not path.is_file() or _sha256_file(path) != item["sha256"]:
                raise ValueError(f"payload package content drifted: {filename}")
    missing = REQUIRED_PACKAGES - names
    if missing:
        raise ValueError(f"payload required packages are missing: {sorted(missing)}")
    if not names.intersection(MICROCODE_PACKAGES):
        raise ValueError("payload required CPU microcode package is missing")
    _validate_dependency_closure(packages)
    material = {key: payload[key] for key in (
        "schema_version", "kind", "metadata_authority", "source_revision", "package_version",
        "runtime_archive_sha256", "repositories", "packages",
    )}
    digest = hashlib.sha256(_canonical(material)).hexdigest()
    if payload.get("payload_sha256") != digest or payload.get("package_generation_id") != f"pkg-{digest}":
        raise ValueError("installer payload digest does not match its contents")
    return dict(payload)


def load_payload_manifest(path: Path, *, package_dir: Path | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("installer payload manifest is unreadable") from exc
    return validate_payload_manifest(value, package_dir=package_dir)
