#!/usr/bin/env python3
"""Transactional virtual-ESP publication and interruption recovery model."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Mapping

from maho_trust_identity import canonical_bytes


PUBLICATION_STEPS = (
    "preflight", "generation_staged", "artifacts_written", "configs_written",
    "checksums_enrolled", "loaders_signed", "metadata_written", "staging_fsynced",
    "previous_preserved", "generation_renamed", "current_pointer_swapped",
    "directory_fsynced", "journal_committed",
)


class PublicationError(RuntimeError):
    pass


@dataclass(frozen=True)
class EspPreflight:
    ok: bool
    reasons: tuple[str, ...]
    available_bytes: int
    required_bytes: int


def _bounded(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise PublicationError("esp_path_unbounded")
    result = (root / pure).resolve()
    try:
        result.relative_to(root.resolve())
    except ValueError as exc:
        raise PublicationError("esp_path_escape") from exc
    return result


def preflight_esp(
    root: str | os.PathLike[str], *, expected_partuuid: str, observed_partuuid: str | None,
    expected_filesystem_identity: str, observed_filesystem_identity: str | None,
    new_generation_bytes: int, previous_generation_bytes: int,
    recovery_reserve_bytes: int, journal_reserve_bytes: int,
) -> EspPreflight:
    path = Path(root)
    reasons: list[str] = []
    if not path.is_dir(): reasons.append("esp_mount_missing")
    if path.is_symlink(): reasons.append("esp_mount_symlink")
    if observed_partuuid != expected_partuuid: reasons.append("esp_partuuid_mismatch")
    if observed_filesystem_identity != expected_filesystem_identity: reasons.append("esp_filesystem_identity_mismatch")
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        free = 0
        reasons.append("esp_free_space_unknown")
    required = new_generation_bytes + previous_generation_bytes + recovery_reserve_bytes + journal_reserve_bytes
    if min(new_generation_bytes, previous_generation_bytes, recovery_reserve_bytes, journal_reserve_bytes) < 0:
        reasons.append("esp_reservation_invalid")
    elif free < required:
        reasons.append("esp_space_insufficient")
    return EspPreflight(not reasons, tuple(sorted(set(reasons))), free, required)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.new")
    with temporary.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _manifest(files: Mapping[str, bytes]) -> bytes:
    return canonical_bytes({"schema_version": 1, "files": {
        path: hashlib.sha256(content).hexdigest() for path, content in sorted(files.items())
    }})


def verify_published_generation(root: Path, generation_id: str) -> bool:
    directory = root / "EFI/MahoOS/Generations" / generation_id
    try:
        manifest = json.loads((directory / "generation.json").read_bytes())
    except (OSError, json.JSONDecodeError):
        return False
    if set(manifest) != {"schema_version", "files"} or manifest["schema_version"] != 1 or not isinstance(manifest["files"], dict):
        return False
    for relative, expected in manifest["files"].items():
        try:
            path = _bounded(directory, relative)
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                return False
        except (OSError, PublicationError):
            return False
    return True


def publish_virtual_generation(
    root: str | os.PathLike[str], generation_id: str, files: Mapping[str, bytes], *,
    fail_after: str | None = None,
) -> None:
    """Publish only fully staged generations; suitable for virtual ESP certification."""
    esp = Path(root).resolve()
    if fail_after is not None and fail_after not in PUBLICATION_STEPS:
        raise PublicationError("publication_failure_point_invalid")
    if not generation_id.startswith("bootgen-") or not files:
        raise PublicationError("publication_input_invalid")
    required = {"Normal/limine.efi", "Normal/limine.conf",
                "Recovery/limine.efi", "Recovery/limine.conf"}
    if not required.issubset(files):
        raise PublicationError("normal_recovery_publication_incomplete")
    base = esp / "EFI/MahoOS"
    staging = base / ".staging" / generation_id
    final = base / "Generations" / generation_id
    journal = base / "publication.json"

    def checkpoint(step: str) -> None:
        _atomic_write(journal, canonical_bytes({"schema_version": 1, "generation_id": generation_id, "step": step}))
        if fail_after == step:
            raise PublicationError(f"simulated_power_loss:{step}")

    checkpoint("preflight")
    staging.mkdir(parents=True, exist_ok=False)
    checkpoint("generation_staged")
    for relative, content in sorted(files.items()):
        target = _bounded(staging, relative)
        _atomic_write(target, content)
    checkpoint("artifacts_written")
    checkpoint("configs_written")
    checkpoint("checksums_enrolled")
    checkpoint("loaders_signed")
    _atomic_write(staging / "generation.json", _manifest(files))
    checkpoint("metadata_written")
    checkpoint("staging_fsynced")
    try:
        previous = (base / "current").read_text().strip()
    except OSError:
        previous = ""
    if previous and verify_published_generation(esp, previous):
        _atomic_write(base / "previous", (previous + "\n").encode("ascii"))
    checkpoint("previous_preserved")
    final.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, final)
    checkpoint("generation_renamed")
    if not verify_published_generation(esp, generation_id):
        raise PublicationError("staged_generation_verification_failed")
    _atomic_write(base / "current", (generation_id + "\n").encode("ascii"))
    checkpoint("current_pointer_swapped")
    checkpoint("directory_fsynced")
    checkpoint("journal_committed")


def recover_virtual_publication(root: str | os.PathLike[str]) -> str:
    """Return previous, new, or recovery-required; never bless partial bytes."""
    esp = Path(root).resolve()
    base = esp / "EFI/MahoOS"
    try:
        current = (base / "current").read_text().strip()
    except OSError:
        return "recovery-required"
    if current.startswith("bootgen-") and verify_published_generation(esp, current):
        try:
            journal_generation = json.loads((base / "publication.json").read_bytes()).get("generation_id")
        except (OSError, json.JSONDecodeError, AttributeError):
            journal_generation = None
        return "new" if current == journal_generation else "previous"
    try:
        previous = (base / "previous").read_text().strip()
    except OSError:
        return "recovery-required"
    if previous.startswith("bootgen-") and verify_published_generation(esp, previous):
        return "previous"
    return "recovery-required"
