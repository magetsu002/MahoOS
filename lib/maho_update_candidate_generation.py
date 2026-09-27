#!/usr/bin/env python3
"""Preactivation generation publication for S2.2 update candidates.

Candidate manifests are durable but non-authoritative: trust remains UNKNOWN
and live.json is never changed until independent postboot verification succeeds.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any, Mapping

from maho_generation_v2 import RootIdentity, SystemGeneration
from maho_kernel_generation import CompatibilityEvidence, KernelGeneration, can_boot
from maho_live_generation import GENERATION_ROOT, read_live_publication
from maho_trust_identity import (
    ArtifactID, GenerationID, ProvenanceID, TransactionID, TrustState,
    canonical_bytes,
)
from maho_update_state import UpdateState, validate_transaction


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_bytes(dict(value))


def _write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o755)
    if path.is_symlink():
        raise ValueError("candidate generation evidence path cannot be a symlink")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _artifact(store: Path, data: bytes) -> ArtifactID:
    identity = ArtifactID.from_content(data)
    digest = str(identity).removeprefix("art-")
    path = store / "sha256" / digest[:2] / digest[2:]
    if path.is_file():
        if path.read_bytes() != data:
            raise ValueError("candidate generation artifact store collision")
    else:
        _write_atomic(path, data)
    return identity


def load_current_verified_generations(
    root: Path = GENERATION_ROOT,
) -> tuple[dict[str, Any], SystemGeneration, KernelGeneration]:
    publication = read_live_publication(root)
    if publication is None:
        raise RuntimeError("current verified SystemGeneration is unavailable")
    try:
        system_value = json.loads((
            root / "manifests/system" / f"{publication['system_generation_id']}.json"
        ).read_text(encoding="utf-8"))
        kernel_value = json.loads((
            root / "manifests/kernel" / f"{publication['kernel_generation_id']}.json"
        ).read_text(encoding="utf-8"))
        system = SystemGeneration.parse(system_value)
        kernel = KernelGeneration.parse(kernel_value)
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError) as exc:
        raise RuntimeError("current generation manifests are unavailable") from exc
    if system.trust_state is not TrustState.VERIFIED or kernel.trust_state is not TrustState.VERIFIED:
        raise RuntimeError("current generation is not independently verified")
    return publication, system, kernel


def _candidate_root_manifest(
    transaction: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    current_system_generation_id: str,
    current_kernel_generation_id: str,
    activation_authority: Mapping[str, Any],
    recovery_evidence: Mapping[str, Any],
    candidate_boot_identity: Mapping[str, Any],
) -> dict[str, Any]:
    tx = validate_transaction(transaction)
    return {
        "schema_version": 1,
        "kind": "maho-update-candidate-root-proof",
        "transaction_id": tx["transaction_id"],
        "source_revision": tx["source_revision"],
        "package_generation_id": tx["package_generation"]["id"],
        "source_provenance_id": tx["source_provenance"]["id"],
        "candidate_uuid": candidate["uuid"],
        "filesystem_uuid": candidate["filesystem_uuid"],
        "parent_root_uuid": candidate["parent_root_uuid"],
        "current_system_generation_id": current_system_generation_id,
        "current_kernel_generation_id": current_kernel_generation_id,
        "activation_authority_id": activation_authority.get("authority_id"),
        "guardian_graph_id": activation_authority.get("graph_id"),
        "recovery_evidence": dict(recovery_evidence),
        "candidate_boot_identity": dict(candidate_boot_identity),
        "preactivation_trust": TrustState.UNKNOWN.value,
    }


def publish_normal_candidate_generation(
    transaction: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    activation_authority: Mapping[str, Any],
    recovery_evidence: Mapping[str, Any],
    candidate_boot_identity: Mapping[str, Any],
    root: Path = GENERATION_ROOT,
) -> dict[str, Any]:
    tx = validate_transaction(transaction)
    if tx["state"] != UpdateState.INSTALLED_PENDING_ACTIVATION.value:
        raise ValueError("normal candidate publication requires pending activation transaction")
    required_candidate = {"uuid", "filesystem_uuid", "parent_root_uuid"}
    if not required_candidate.issubset(candidate):
        raise ValueError("candidate generation root identity is incomplete")
    if recovery_evidence.get("ready") is not True:
        raise ValueError("candidate generation requires exact recovery evidence")
    if not activation_authority.get("authority_id"):
        raise ValueError("candidate generation requires activation authority")

    live, current_system, current_kernel = load_current_verified_generations(root)
    if str(current_system.generation_id) != live["system_generation_id"]:
        raise ValueError("current SystemGeneration publication drifted")
    if str(current_kernel.kernel_generation_id) != live["kernel_generation_id"]:
        raise ValueError("current KernelGeneration publication drifted")
    if candidate["parent_root_uuid"] != live.get("root_subvolume_uuid"):
        raise ValueError("candidate parent root is not current verified generation")

    root_manifest = _candidate_root_manifest(
        tx,
        candidate=candidate,
        current_system_generation_id=str(current_system.generation_id),
        current_kernel_generation_id=str(current_kernel.kernel_generation_id),
        activation_authority=activation_authority,
        recovery_evidence=recovery_evidence,
        candidate_boot_identity=candidate_boot_identity,
    )
    root_bytes = _json_bytes(root_manifest)
    store = root / "artifacts"
    root_artifact = _artifact(store, root_bytes)
    authority_artifact = _artifact(store, _json_bytes(dict(activation_authority)))
    recovery_artifact = _artifact(store, _json_bytes(dict(recovery_evidence)))
    boot_artifact = _artifact(store, _json_bytes(dict(candidate_boot_identity)))

    transaction_id = TransactionID.derive({
        "kind": "maho-update-candidate-transaction",
        "transaction_id": tx["transaction_id"],
        "source_revision": tx["source_revision"],
        "package_generation_id": tx["package_generation"]["id"],
        "candidate_uuid": candidate["uuid"],
    })
    provenance = ProvenanceID.derive({
        "kind": "maho-update-preactivation-candidate",
        "transaction_id": tx["transaction_id"],
        "activation_authority_id": activation_authority.get("authority_id"),
        "current_system_generation_id": str(current_system.generation_id),
    })
    system = SystemGeneration.create(
        parent_generation_id=current_system.generation_id,
        root_identity=RootIdentity(
            f"btrfs-uuid:{candidate['uuid']}",
            f"uuid:{candidate['filesystem_uuid']}",
            hashlib.sha256(root_bytes).hexdigest(),
        ),
        kernel_generation_id=current_kernel.kernel_generation_id,
        package_set_identity=tx["package_generation"]["id"],
        transaction_id=transaction_id,
        provenance_id=provenance,
        artifact_ids=(root_artifact, authority_artifact, recovery_artifact, boot_artifact),
        trust_state=TrustState.UNKNOWN,
    )
    publication = {
        "schema_version": 1,
        "kind": "maho-update-candidate-generation-publication",
        "transaction_id": tx["transaction_id"],
        "source_revision": tx["source_revision"],
        "package_generation_id": tx["package_generation"]["id"],
        "system_generation_id": str(system.generation_id),
        "kernel_generation_id": str(current_kernel.kernel_generation_id),
        "kernel_generation_changed": False,
        "boot_generation_changed": False,
        "parent_system_generation_id": str(current_system.generation_id),
        "root_manifest_artifact_id": str(root_artifact),
        "candidate_uuid": candidate["uuid"],
        "filesystem_uuid": candidate["filesystem_uuid"],
        "parent_root_uuid": candidate["parent_root_uuid"],
        "trust_state": TrustState.UNKNOWN.value,
        "activation_authority_id": activation_authority.get("authority_id"),
        "candidate_boot_identity": dict(candidate_boot_identity),
        "recovery_evidence": dict(recovery_evidence),
    }
    publication["publication_id"] = str(ArtifactID.from_content(_json_bytes(publication)))

    _write_atomic(
        root / "manifests/system" / f"{system.generation_id}.json",
        (system.canonical_manifest() + "\n").encode(),
    )
    _write_atomic(
        root / "candidate-publications" / f"{tx['transaction_id']}.json",
        _json_bytes(publication) + b"\n",
    )
    return publication


def read_candidate_publication(
    transaction_id: str, root: Path = GENERATION_ROOT,
) -> dict[str, Any] | None:
    path = root / "candidate-publications" / f"{transaction_id}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("kind") != "maho-update-candidate-generation-publication":
        return None
    claimed = value.get("publication_id")
    material = dict(value)
    material.pop("publication_id", None)
    if claimed != str(ArtifactID.from_content(_json_bytes(material))):
        return None
    try:
        system = SystemGeneration.parse(json.loads((
            root / "manifests/system" / f"{value['system_generation_id']}.json"
        ).read_text(encoding="utf-8")))
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, ValueError):
        return None
    if (
        str(system.generation_id) != value.get("system_generation_id")
        or system.trust_state is not TrustState.UNKNOWN
        or str(system.parent_generation_id) != value.get("parent_system_generation_id")
    ):
        return None
    return value


def promote_normal_candidate_generation(
    transaction: Mapping[str, Any],
    *,
    live_root_uuid: str,
    filesystem_uuid: str,
    running_kernel_abi: str,
    package_versions: Mapping[str, str],
    boot_sha256: Mapping[str, str],
    verifier_identity: str,
    root: Path = GENERATION_ROOT,
) -> dict[str, Any]:
    """Promote an exact normal candidate after independent postboot success.

    Failure is reported to the caller; this function contains no recovery path.
    """
    tx = validate_transaction(transaction)
    if tx["state"] != UpdateState.HEALTHY.value:
        raise ValueError("candidate generation promotion requires HEALTHY transaction")
    candidate = read_candidate_publication(tx["transaction_id"], root)
    if candidate is None:
        raise ValueError("candidate generation publication is unavailable")
    if live_root_uuid != candidate["candidate_uuid"] or filesystem_uuid != candidate["filesystem_uuid"]:
        raise ValueError("live root does not match candidate SystemGeneration")
    expected_versions = {
        item["name"]: item["candidate_version"]
        for item in tx["package_generation"]["packages"]
    }
    if dict(package_versions) != expected_versions:
        raise ValueError("live package set does not match candidate PackageGeneration")
    if dict(boot_sha256) != dict(candidate["candidate_boot_identity"].get("sha256", {})):
        raise ValueError("postboot boot identity drifted")
    if not verifier_identity:
        raise ValueError("postboot verifier identity is required")

    system_path = root / "manifests/system" / f"{candidate['system_generation_id']}.json"
    system = SystemGeneration.parse(json.loads(system_path.read_text(encoding="utf-8")))
    kernel_path = root / "manifests/kernel" / f"{candidate['kernel_generation_id']}.json"
    kernel = KernelGeneration.parse(json.loads(kernel_path.read_text(encoding="utf-8")))
    if kernel.trust_state is not TrustState.VERIFIED:
        raise ValueError("unchanged KernelGeneration is no longer verified")
    if running_kernel_abi != kernel.kernel_abi:
        raise ValueError("running kernel ABI drifted from unchanged KernelGeneration")

    verified_system = SystemGeneration(
        generation_id=system.generation_id,
        parent_generation_id=system.parent_generation_id,
        root_identity=system.root_identity,
        kernel_generation_id=system.kernel_generation_id,
        package_set_identity=system.package_set_identity,
        transaction_id=system.transaction_id,
        provenance_id=system.provenance_id,
        artifact_ids=system.artifact_ids,
        trust_state=TrustState.VERIFIED,
        metadata_status=system.metadata_status,
        legacy_generation_id=system.legacy_generation_id,
    )
    compatibility = CompatibilityEvidence(
        system_generation_id=verified_system.generation_id,
        kernel_generation_id=kernel.kernel_generation_id,
        root_manifest_sha256=verified_system.root_identity.root_manifest_sha256,
        filesystem_identity=verified_system.root_identity.filesystem_identity,
        kernel_abi=kernel.kernel_abi,
        modules_abi=kernel.modules_abi,
        verifier_identity=verifier_identity,
        independently_verified=True,
    )
    if not can_boot(kernel, verified_system, compatibility):
        raise ValueError("candidate SystemGeneration compatibility proof failed")

    compatibility_payload = {
        "schema_version": 1,
        "system_generation_id": str(compatibility.system_generation_id),
        "kernel_generation_id": str(compatibility.kernel_generation_id),
        "root_manifest_sha256": compatibility.root_manifest_sha256,
        "filesystem_identity": compatibility.filesystem_identity,
        "kernel_abi": compatibility.kernel_abi,
        "modules_abi": compatibility.modules_abi,
        "verifier_identity": compatibility.verifier_identity,
        "independently_verified": True,
    }
    live = {
        "schema_version": 1,
        "kind": "maho-live-generation-publication",
        "system_generation_id": str(verified_system.generation_id),
        "kernel_generation_id": str(kernel.kernel_generation_id),
        "transaction_id": tx["transaction_id"],
        "native_transaction_id": str(verified_system.transaction_id),
        "source_revision": tx["source_revision"],
        "publisher_source_revision": tx["source_revision"],
        "package_generation_id": tx["package_generation"]["id"],
        "filesystem_uuid": filesystem_uuid,
        "root_subvolume_uuid": live_root_uuid,
        "fsroot": "/@",
        "running_kernel": running_kernel_abi,
        "cmdline_sha256": candidate.get("candidate_boot_identity", {}).get("cmdline_sha256", ""),
        "boot_sha256": dict(boot_sha256),
        "root_manifest_artifact_id": candidate["root_manifest_artifact_id"],
        "recovery_generation_id": candidate.get("recovery_evidence", {}).get("generation_id"),
        "previous_root_uuid": candidate["parent_root_uuid"],
        "previous_root_read_only": True,
    }
    live["publication_id"] = str(ArtifactID.from_content(_json_bytes(live)))

    _write_atomic(system_path, (verified_system.canonical_manifest() + "\n").encode())
    _write_atomic(
        root / "evidence/compatibility" /
        f"{verified_system.generation_id}--{kernel.kernel_generation_id}.json",
        _json_bytes(compatibility_payload) + b"\n",
    )
    _write_atomic(root / "live.json", _json_bytes(live) + b"\n")
    return live
