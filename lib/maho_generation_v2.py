#!/usr/bin/env python3
"""Graph-shaped SystemGeneration manifests with explicit G3 compatibility."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from maho_trust_identity import (
    ArtifactID, GenerationID, KernelGenerationID, ProvenanceID, TransactionID,
    TrustState, canonical_json, parse_trust_state,
)


SCHEMA_VERSION = 2
FULL = "FULL"
LEGACY_PARTIAL = "LEGACY_PARTIAL"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_FILESYSTEM = re.compile(r"(?:uuid|partuuid):[0-9a-fA-F-]{8,64}")
_PACKAGE_SET = re.compile(r"(?:pkg|art)-[0-9a-f]{64}")
_FIELDS = {
    "schema_version", "generation_id", "parent_generation_id", "root_identity",
    "kernel_generation_id", "package_set_identity", "transaction_id",
    "provenance_id", "artifact_ids", "trust_state", "metadata_status",
    "legacy_generation_id",
}


@dataclass(frozen=True)
class RootIdentity:
    snapshot_identity: str
    filesystem_identity: str
    root_manifest_sha256: str

    def __post_init__(self) -> None:
        if not self.snapshot_identity or self.snapshot_identity.startswith("/dev/"):
            raise ValueError("snapshot identity must be stable and cannot be a device path")
        if _FILESYSTEM.fullmatch(self.filesystem_identity) is None:
            raise ValueError("filesystem identity must use UUID or PARTUUID authority")
        if _SHA256.fullmatch(self.root_manifest_sha256) is None:
            raise ValueError("root manifest identity must be lowercase SHA-256")

    def as_dict(self) -> dict[str, str]:
        return {
            "snapshot_identity": self.snapshot_identity,
            "filesystem_identity": self.filesystem_identity.lower(),
            "root_manifest_sha256": self.root_manifest_sha256,
        }

    @classmethod
    def parse(cls, payload: Any) -> "RootIdentity":
        if not isinstance(payload, Mapping) or set(payload) != {
            "snapshot_identity", "filesystem_identity", "root_manifest_sha256",
        }:
            raise ValueError("root identity fields are invalid")
        return cls(
            snapshot_identity=payload["snapshot_identity"],
            filesystem_identity=payload["filesystem_identity"],
            root_manifest_sha256=payload["root_manifest_sha256"],
        )


@dataclass(frozen=True)
class SystemGeneration:
    generation_id: GenerationID
    parent_generation_id: GenerationID | None
    root_identity: RootIdentity | None
    kernel_generation_id: KernelGenerationID | None
    package_set_identity: str | None
    transaction_id: TransactionID | None
    provenance_id: ProvenanceID | None
    artifact_ids: tuple[ArtifactID, ...]
    trust_state: TrustState
    metadata_status: str = FULL
    legacy_generation_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported SystemGeneration schema")
        if self.metadata_status not in {FULL, LEGACY_PARTIAL}:
            raise ValueError("unknown generation metadata status")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("generation artifact references must be unique")
        if tuple(sorted(self.artifact_ids)) != self.artifact_ids:
            raise ValueError("generation artifact references must be canonical")
        parse_trust_state(self.trust_state)
        if self.metadata_status == FULL:
            if None in (self.root_identity, self.kernel_generation_id, self.package_set_identity, self.transaction_id, self.provenance_id):
                raise ValueError("complete generation metadata is required")
            if _PACKAGE_SET.fullmatch(str(self.package_set_identity)) is None:
                raise ValueError("package-set identity is malformed")
            if self.legacy_generation_id is not None:
                raise ValueError("complete generation cannot claim a legacy identity")
        else:
            if not isinstance(self.legacy_generation_id, str) or not self.legacy_generation_id.startswith("g3-"):
                raise ValueError("legacy generation identity is required")
            if self.trust_state in {TrustState.VERIFIED, TrustState.REVALIDATED}:
                raise ValueError("partial legacy metadata cannot be trusted implicitly")
        if self.generation_id != GenerationID.derive(self.identity_material()):
            raise ValueError("SystemGeneration identity does not match canonical manifest")

    def identity_material(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "parent_generation_id": str(self.parent_generation_id) if self.parent_generation_id else None,
            "root_identity": self.root_identity.as_dict() if self.root_identity else None,
            "kernel_generation_id": str(self.kernel_generation_id) if self.kernel_generation_id else None,
            "package_set_identity": self.package_set_identity,
            "transaction_id": str(self.transaction_id) if self.transaction_id else None,
            "provenance_id": str(self.provenance_id) if self.provenance_id else None,
            "artifact_ids": [str(item) for item in self.artifact_ids],
            "metadata_status": self.metadata_status,
            "legacy_generation_id": self.legacy_generation_id,
        }

    @classmethod
    def create(
        cls, *, parent_generation_id: GenerationID | None, root_identity: RootIdentity,
        kernel_generation_id: KernelGenerationID, package_set_identity: str,
        transaction_id: TransactionID, provenance_id: ProvenanceID,
        artifact_ids: Iterable[ArtifactID], trust_state: TrustState = TrustState.UNKNOWN,
    ) -> "SystemGeneration":
        artifacts = tuple(sorted(ArtifactID(str(item)) for item in artifact_ids))
        seed = {
            "schema_version": SCHEMA_VERSION,
            "parent_generation_id": str(parent_generation_id) if parent_generation_id else None,
            "root_identity": root_identity.as_dict(),
            "kernel_generation_id": str(kernel_generation_id),
            "package_set_identity": package_set_identity,
            "transaction_id": str(transaction_id),
            "provenance_id": str(provenance_id),
            "artifact_ids": [str(item) for item in artifacts],
            "metadata_status": FULL,
            "legacy_generation_id": None,
        }
        return cls(
            generation_id=GenerationID.derive(seed), parent_generation_id=parent_generation_id,
            root_identity=root_identity, kernel_generation_id=kernel_generation_id,
            package_set_identity=package_set_identity, transaction_id=transaction_id,
            provenance_id=provenance_id, artifact_ids=artifacts, trust_state=trust_state,
        )

    def as_dict(self) -> dict[str, Any]:
        return self.identity_material() | {
            "generation_id": str(self.generation_id),
            "trust_state": self.trust_state.value,
        }

    def canonical_manifest(self) -> str:
        return canonical_json(self.as_dict())

    @classmethod
    def parse(cls, payload: Mapping[str, Any]) -> "SystemGeneration":
        if not isinstance(payload, Mapping):
            raise ValueError("SystemGeneration manifest must be an object")
        unknown = set(payload) - _FIELDS
        missing = _FIELDS - set(payload)
        if unknown or missing:
            raise ValueError(f"SystemGeneration fields invalid: unknown={sorted(unknown)} missing={sorted(missing)}")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported SystemGeneration schema")
        parent = payload["parent_generation_id"]
        kernel = payload["kernel_generation_id"]
        transaction = payload["transaction_id"]
        provenance = payload["provenance_id"]
        artifacts = payload["artifact_ids"]
        if not isinstance(artifacts, list):
            raise ValueError("artifact_ids must be a list")
        return cls(
            generation_id=GenerationID(payload["generation_id"]),
            parent_generation_id=GenerationID(parent) if parent is not None else None,
            root_identity=RootIdentity.parse(payload["root_identity"]) if payload["root_identity"] is not None else None,
            kernel_generation_id=KernelGenerationID(kernel) if kernel is not None else None,
            package_set_identity=payload["package_set_identity"],
            transaction_id=TransactionID(transaction) if transaction is not None else None,
            provenance_id=ProvenanceID(provenance) if provenance is not None else None,
            artifact_ids=tuple(ArtifactID(item) for item in artifacts),
            trust_state=parse_trust_state(payload["trust_state"]),
            metadata_status=payload["metadata_status"],
            legacy_generation_id=payload["legacy_generation_id"],
        )


def from_legacy_recovery(payload: Mapping[str, Any]) -> SystemGeneration:
    """Map a historical G3 record without manufacturing missing trust evidence."""
    if not isinstance(payload, Mapping):
        raise ValueError("legacy recovery generation must be an object")
    legacy_id = payload.get("generation_id")
    if not isinstance(legacy_id, str) or not re.fullmatch(r"g3-[0-9a-f]{24}", legacy_id):
        raise ValueError("legacy recovery generation identity is invalid")
    fsuuid = payload.get("root_filesystem_uuid")
    snapshot = payload.get("snapshot")
    root: RootIdentity | None = None
    if isinstance(fsuuid, str) and isinstance(snapshot, Mapping):
        config = snapshot.get("config_name")
        number = snapshot.get("snapshot_id")
        manifest = payload.get("root_manifest_sha256")
        if isinstance(config, str) and isinstance(number, int) and _SHA256.fullmatch(str(manifest or "")):
            root = RootIdentity(f"snapper:{config}:{number}", f"uuid:{fsuuid}", str(manifest))
    seed = {
        "schema_version": SCHEMA_VERSION, "parent_generation_id": None,
        "root_identity": root.as_dict() if root else None, "kernel_generation_id": None,
        "package_set_identity": None, "transaction_id": None, "provenance_id": None,
        "artifact_ids": [], "metadata_status": LEGACY_PARTIAL,
        "legacy_generation_id": legacy_id,
    }
    return SystemGeneration(
        generation_id=GenerationID.derive(seed), parent_generation_id=None,
        root_identity=root, kernel_generation_id=None, package_set_identity=None,
        transaction_id=None, provenance_id=None, artifact_ids=(),
        trust_state=TrustState.UNKNOWN, metadata_status=LEGACY_PARTIAL,
        legacy_generation_id=legacy_id,
    )


class GenerationGraph:
    def __init__(
        self, generations: Iterable[SystemGeneration], *,
        artifact_transactions: Mapping[ArtifactID, TransactionID] | None = None,
        expected_filesystems: Mapping[GenerationID, str] | None = None,
    ) -> None:
        items = list(generations)
        ids = [item.generation_id for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate SystemGeneration identity")
        self.generations = {item.generation_id: item for item in items}
        self.artifact_transactions = dict(artifact_transactions or {})
        for item in items:
            if item.parent_generation_id is not None and item.parent_generation_id not in self.generations:
                raise ValueError(f"missing parent for {item.generation_id}")
            expected = (expected_filesystems or {}).get(item.generation_id)
            if expected is not None and (item.root_identity is None or item.root_identity.filesystem_identity.lower() != expected.lower()):
                raise ValueError(f"filesystem identity mismatch for {item.generation_id}")
            for artifact_id in item.artifact_ids:
                observed = self.artifact_transactions.get(artifact_id)
                if observed is not None and observed != item.transaction_id:
                    raise ValueError(f"transaction mismatch for artifact {artifact_id}")
        for generation_id in ids:
            self._assert_acyclic(generation_id)

    def _assert_acyclic(self, start: GenerationID) -> None:
        seen: set[GenerationID] = set()
        current: GenerationID | None = start
        while current is not None:
            if current in seen:
                raise ValueError("SystemGeneration parent cycle")
            seen.add(current)
            current = self.generations[current].parent_generation_id

    def lineage(self, generation_id: GenerationID) -> tuple[SystemGeneration, ...]:
        if generation_id not in self.generations:
            raise KeyError(str(generation_id))
        result: list[SystemGeneration] = []
        current: GenerationID | None = generation_id
        while current is not None:
            item = self.generations[current]
            result.append(item)
            current = item.parent_generation_id
        return tuple(result)

    def ancestors(self, generation_id: GenerationID) -> tuple[SystemGeneration, ...]:
        return self.lineage(generation_id)[1:]

    def generations_for_artifact(self, artifact_id: ArtifactID) -> tuple[GenerationID, ...]:
        return tuple(sorted(item.generation_id for item in self.generations.values() if artifact_id in item.artifact_ids))

    def transaction_for(self, generation_id: GenerationID) -> TransactionID | None:
        return self.generations[generation_id].transaction_id

    def effective_trust(self, generation_id: GenerationID) -> TrustState:
        lineage = self.lineage(generation_id)
        current = lineage[0].trust_state
        if current in {TrustState.REVOKED, TrustState.CONTAMINATED, TrustState.UNKNOWN}:
            return current
        if current is TrustState.REVALIDATED:
            return TrustState.REVALIDATED
        for ancestor in lineage[1:]:
            if ancestor.trust_state in {TrustState.REVOKED, TrustState.CONTAMINATED}:
                return TrustState.CONTAMINATED
            if ancestor.trust_state is TrustState.UNKNOWN:
                return TrustState.UNKNOWN
        return TrustState.VERIFIED

    def newest_verified_ancestor(self, generation_id: GenerationID) -> SystemGeneration | None:
        return next(
            (item for item in self.lineage(generation_id) if self.effective_trust(item.generation_id) in {TrustState.VERIFIED, TrustState.REVALIDATED}),
            None,
        )
