#!/usr/bin/env python3
"""Content-addressed KernelGeneration manifests and compatibility evidence."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable, Mapping

from maho_generation_v2 import GenerationGraph, SystemGeneration
from maho_trust_identity import (
    ArtifactID, GenerationID, KernelGenerationID, ProvenanceID, TransactionID,
    TrustState, canonical_bytes, canonical_json, parse_trust_state,
)


SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FIELDS = {
    "schema_version", "kernel_generation_id", "parent_kernel_generation_id",
    "kernel_image_id", "initramfs_id", "modules_tree_id", "dkms_output_ids",
    "microcode_ids", "cmdline_contract_sha256", "package_provider_identity",
    "provenance_id", "transaction_id", "kernel_abi", "modules_abi", "trust_state",
}


def modules_tree_artifact(entries: Mapping[str, ArtifactID]) -> tuple[ArtifactID, bytes]:
    """Hash a normalized modules-tree manifest, not a copied operating system."""
    normalized: dict[str, str] = {}
    for raw_path, artifact_id in entries.items():
        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
            raise ValueError("modules tree paths must be relative and bounded")
        normalized[str(path)] = str(ArtifactID(str(artifact_id)))
    payload = canonical_bytes({"schema_version": 1, "entries": normalized})
    return ArtifactID.from_content(payload), payload


class ContentAddressedArtifactStore:
    """Minimal deduplicating store used by staging and offline fixtures."""
    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)

    def path_for(self, artifact_id: ArtifactID) -> Path:
        digest = str(ArtifactID(str(artifact_id))).removeprefix("art-")
        return self.root / "sha256" / digest[:2] / digest[2:]

    def put(self, content: bytes) -> tuple[ArtifactID, Path]:
        artifact_id = ArtifactID.from_content(content)
        target = self.path_for(artifact_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            if ArtifactID.from_content(target.read_bytes()) != artifact_id:
                raise ValueError("content-addressed store collision")
        return artifact_id, target

    def verify(self, artifact_id: ArtifactID) -> bool:
        path = self.path_for(artifact_id)
        try:
            return ArtifactID.from_content(path.read_bytes()) == artifact_id
        except OSError:
            return False


@dataclass(frozen=True)
class KernelGeneration:
    kernel_generation_id: KernelGenerationID
    parent_kernel_generation_id: KernelGenerationID | None
    kernel_image_id: ArtifactID
    initramfs_id: ArtifactID
    modules_tree_id: ArtifactID
    dkms_output_ids: tuple[ArtifactID, ...]
    microcode_ids: tuple[ArtifactID, ...]
    cmdline_contract_sha256: str
    package_provider_identity: str
    provenance_id: ProvenanceID
    transaction_id: TransactionID
    kernel_abi: str
    modules_abi: str
    trust_state: TrustState = TrustState.UNKNOWN
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported KernelGeneration schema")
        if _SHA256.fullmatch(self.cmdline_contract_sha256) is None:
            raise ValueError("kernel command-line contract must be SHA-256")
        if not self.package_provider_identity or not self.kernel_abi or not self.modules_abi:
            raise ValueError("kernel provider and ABI evidence are required")
        for values, name in ((self.dkms_output_ids, "DKMS"), (self.microcode_ids, "microcode")):
            if tuple(sorted(values)) != values or len(set(values)) != len(values):
                raise ValueError(f"{name} artifact references must be unique and canonical")
        parse_trust_state(self.trust_state)
        if self.kernel_generation_id != KernelGenerationID.derive(self.identity_material()):
            raise ValueError("KernelGeneration identity does not match canonical manifest")

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "parent_kernel_generation_id": str(self.parent_kernel_generation_id) if self.parent_kernel_generation_id else None,
            "kernel_image_id": str(self.kernel_image_id),
            "initramfs_id": str(self.initramfs_id),
            "modules_tree_id": str(self.modules_tree_id),
            "dkms_output_ids": [str(item) for item in self.dkms_output_ids],
            "microcode_ids": [str(item) for item in self.microcode_ids],
            "cmdline_contract_sha256": self.cmdline_contract_sha256,
            "package_provider_identity": self.package_provider_identity,
            "provenance_id": str(self.provenance_id),
            "transaction_id": str(self.transaction_id),
            "kernel_abi": self.kernel_abi,
            "modules_abi": self.modules_abi,
        }

    @classmethod
    def create(
        cls, *, parent_kernel_generation_id: KernelGenerationID | None,
        kernel_image_id: ArtifactID, initramfs_id: ArtifactID,
        modules_tree_id: ArtifactID, dkms_output_ids: Iterable[ArtifactID],
        microcode_ids: Iterable[ArtifactID], cmdline_contract: str,
        package_provider_identity: str, provenance_id: ProvenanceID,
        transaction_id: TransactionID, kernel_abi: str, modules_abi: str,
        trust_state: TrustState = TrustState.UNKNOWN,
    ) -> "KernelGeneration":
        dkms = tuple(sorted(ArtifactID(str(item)) for item in dkms_output_ids))
        microcode = tuple(sorted(ArtifactID(str(item)) for item in microcode_ids))
        cmdline_hash = hashlib.sha256(cmdline_contract.encode("utf-8")).hexdigest()
        material = {
            "schema_version": SCHEMA_VERSION,
            "parent_kernel_generation_id": str(parent_kernel_generation_id) if parent_kernel_generation_id else None,
            "kernel_image_id": str(kernel_image_id), "initramfs_id": str(initramfs_id),
            "modules_tree_id": str(modules_tree_id),
            "dkms_output_ids": [str(item) for item in dkms],
            "microcode_ids": [str(item) for item in microcode],
            "cmdline_contract_sha256": cmdline_hash,
            "package_provider_identity": package_provider_identity,
            "provenance_id": str(provenance_id), "transaction_id": str(transaction_id),
            "kernel_abi": kernel_abi, "modules_abi": modules_abi,
        }
        return cls(
            kernel_generation_id=KernelGenerationID.derive(material),
            parent_kernel_generation_id=parent_kernel_generation_id,
            kernel_image_id=kernel_image_id, initramfs_id=initramfs_id,
            modules_tree_id=modules_tree_id, dkms_output_ids=dkms,
            microcode_ids=microcode, cmdline_contract_sha256=cmdline_hash,
            package_provider_identity=package_provider_identity,
            provenance_id=provenance_id, transaction_id=transaction_id,
            kernel_abi=kernel_abi, modules_abi=modules_abi, trust_state=trust_state,
        )

    @property
    def artifact_ids(self) -> tuple[ArtifactID, ...]:
        return (
            self.kernel_image_id, self.initramfs_id, self.modules_tree_id,
            *self.dkms_output_ids, *self.microcode_ids,
        )

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {
            "kernel_generation_id": str(self.kernel_generation_id),
            "trust_state": self.trust_state.value,
        }

    def canonical_manifest(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "KernelGeneration":
        if not isinstance(payload, Mapping) or set(payload) != _FIELDS:
            raise ValueError("KernelGeneration fields are invalid")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported KernelGeneration schema")
        for name in ("dkms_output_ids", "microcode_ids"):
            if not isinstance(payload[name], list):
                raise ValueError(f"{name} must be a list")
        parent = payload["parent_kernel_generation_id"]
        return cls(
            kernel_generation_id=KernelGenerationID(payload["kernel_generation_id"]),
            parent_kernel_generation_id=KernelGenerationID(parent) if parent else None,
            kernel_image_id=ArtifactID(payload["kernel_image_id"]),
            initramfs_id=ArtifactID(payload["initramfs_id"]),
            modules_tree_id=ArtifactID(payload["modules_tree_id"]),
            dkms_output_ids=tuple(ArtifactID(item) for item in payload["dkms_output_ids"]),
            microcode_ids=tuple(ArtifactID(item) for item in payload["microcode_ids"]),
            cmdline_contract_sha256=payload["cmdline_contract_sha256"],
            package_provider_identity=payload["package_provider_identity"],
            provenance_id=ProvenanceID(payload["provenance_id"]),
            transaction_id=TransactionID(payload["transaction_id"]),
            kernel_abi=payload["kernel_abi"], modules_abi=payload["modules_abi"],
            trust_state=parse_trust_state(payload["trust_state"]),
        )


def verify_artifacts(
    generation: KernelGeneration, observed: Mapping[ArtifactID, bytes],
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    for artifact_id in generation.artifact_ids:
        content = observed.get(artifact_id)
        if content is None:
            reasons.append(f"missing:{artifact_id}")
        elif ArtifactID.from_content(content) != artifact_id:
            reasons.append(f"digest_mismatch:{artifact_id}")
    if generation.kernel_abi != generation.modules_abi:
        reasons.append("kernel_modules_abi_mismatch")
    return not reasons, tuple(reasons)


@dataclass(frozen=True)
class CompatibilityEvidence:
    system_generation_id: GenerationID
    kernel_generation_id: KernelGenerationID
    root_manifest_sha256: str
    filesystem_identity: str
    kernel_abi: str
    modules_abi: str
    verifier_identity: str
    independently_verified: bool


def can_boot(
    kernel: KernelGeneration, system: SystemGeneration,
    evidence: CompatibilityEvidence | None,
) -> bool:
    if evidence is None or not evidence.independently_verified or not evidence.verifier_identity:
        return False
    if system.root_identity is None or system.kernel_generation_id != kernel.kernel_generation_id:
        return False
    return all((
        evidence.system_generation_id == system.generation_id,
        evidence.kernel_generation_id == kernel.kernel_generation_id,
        evidence.root_manifest_sha256 == system.root_identity.root_manifest_sha256,
        evidence.filesystem_identity.lower() == system.root_identity.filesystem_identity.lower(),
        evidence.kernel_abi == kernel.kernel_abi,
        evidence.modules_abi == kernel.modules_abi,
        kernel.kernel_abi == kernel.modules_abi,
    ))


class KernelGenerationGraph:
    def __init__(self, generations: Iterable[KernelGeneration]) -> None:
        items = list(generations)
        ids = [item.kernel_generation_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate KernelGeneration identity")
        self.generations = {item.kernel_generation_id: item for item in items}
        for item in items:
            if item.parent_kernel_generation_id is not None and item.parent_kernel_generation_id not in self.generations:
                raise ValueError("missing KernelGeneration parent")
        for item in items:
            self.lineage(item.kernel_generation_id)

    def lineage(self, start: KernelGenerationID) -> tuple[KernelGeneration, ...]:
        result: list[KernelGeneration] = []
        seen: set[KernelGenerationID] = set()
        current: KernelGenerationID | None = start
        while current is not None:
            if current in seen:
                raise ValueError("KernelGeneration parent cycle")
            seen.add(current)
            item = self.generations[current]
            result.append(item)
            current = item.parent_kernel_generation_id
        return tuple(result)

    def effective_trust(self, start: KernelGenerationID) -> TrustState:
        lineage = self.lineage(start)
        if lineage[0].trust_state is TrustState.REVALIDATED:
            return TrustState.REVALIDATED
        if lineage[0].trust_state in {TrustState.UNKNOWN, TrustState.REVOKED, TrustState.CONTAMINATED}:
            return lineage[0].trust_state
        for ancestor in lineage[1:]:
            if ancestor.trust_state in {TrustState.REVOKED, TrustState.CONTAMINATED}:
                return TrustState.CONTAMINATED
            if ancestor.trust_state is TrustState.UNKNOWN:
                return TrustState.UNKNOWN
        return TrustState.VERIFIED

    def newest_verified_ancestor(self, start: KernelGenerationID) -> KernelGeneration | None:
        return next((item for item in self.lineage(start) if self.effective_trust(item.kernel_generation_id) in {TrustState.VERIFIED, TrustState.REVALIDATED}), None)

    def first_introducing(
        self, artifact_id: ArtifactID, *, descendant: KernelGenerationID | None = None,
    ) -> KernelGeneration | None:
        """Return the oldest occurrence in one lineage (or the shallowest globally)."""
        if descendant is not None:
            lineage = reversed(self.lineage(descendant))
            return next((item for item in lineage if artifact_id in item.artifact_ids), None)
        candidates = [item for item in self.generations.values() if artifact_id in item.artifact_ids]
        return min(
            candidates,
            key=lambda item: (len(self.lineage(item.kernel_generation_id)), str(item.kernel_generation_id)),
            default=None,
        )


def system_generations_referencing(graph: GenerationGraph, kernel_id: KernelGenerationID) -> tuple[GenerationID, ...]:
    return tuple(sorted(item.generation_id for item in graph.generations.values() if item.kernel_generation_id == kernel_id))


def newest_verified_pair(
    current_system_id: GenerationID, system_graph: GenerationGraph,
    kernel_graph: KernelGenerationGraph,
    evidence: Mapping[tuple[GenerationID, KernelGenerationID], CompatibilityEvidence],
) -> tuple[SystemGeneration, KernelGeneration] | None:
    for system in system_graph.lineage(current_system_id):
        if system_graph.effective_trust(system.generation_id) not in {TrustState.VERIFIED, TrustState.REVALIDATED}:
            continue
        kernel_id = system.kernel_generation_id
        if kernel_id is None or kernel_id not in kernel_graph.generations:
            continue
        kernel = kernel_graph.generations[kernel_id]
        if kernel_graph.effective_trust(kernel_id) not in {TrustState.VERIFIED, TrustState.REVALIDATED}:
            continue
        if can_boot(kernel, system, evidence.get((system.generation_id, kernel_id))):
            return system, kernel
    return None
