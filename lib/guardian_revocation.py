#!/usr/bin/env python3
"""Retroactive revocation propagation across Maho generation graphs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Any, Iterable, Mapping

from maho_generation_v2 import GenerationGraph, SystemGeneration
from maho_kernel_generation import KernelGenerationGraph
from maho_trust_identity import (
    ArtifactID, GenerationID, KernelGenerationID, TransactionID, TrustState,
    canonical_bytes,
)


_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")


@dataclass(frozen=True)
class ArtifactEvidence:
    artifact_id: ArtifactID
    transaction_id: TransactionID
    signing_authority: str | None
    signed_at: str

    def __post_init__(self) -> None:
        if _STAMP.fullmatch(self.signed_at) is None:
            raise ValueError("artifact signing time must be canonical UTC")


@dataclass(frozen=True)
class RevocationRecord:
    revocation_id: str
    target_kind: str
    target_id: str
    source: str
    reason: str
    issued_at: str
    effective_from: str | None = None
    effective_until: str | None = None

    def __post_init__(self) -> None:
        if not re.fullmatch(r"rev-[0-9a-f]{64}", self.revocation_id):
            raise ValueError("revocation identity is invalid")
        if self.target_kind not in {"ARTIFACT", "SIGNING_AUTHORITY"}:
            raise ValueError("revocation target kind is invalid")
        if not self.target_id or not self.source or not self.reason or _STAMP.fullmatch(self.issued_at) is None:
            raise ValueError("revocation evidence is incomplete")
        if self.target_kind == "ARTIFACT":
            ArtifactID(self.target_id)
        for stamp in (self.effective_from, self.effective_until):
            if stamp is not None and _STAMP.fullmatch(stamp) is None:
                raise ValueError("revocation interval is invalid")
        if self.effective_from and self.effective_until and self.effective_from > self.effective_until:
            raise ValueError("revocation interval is reversed")

    @classmethod
    def create(
        cls, *, target_kind: str, target_id: str, source: str, reason: str,
        issued_at: str, effective_from: str | None = None,
        effective_until: str | None = None,
    ) -> "RevocationRecord":
        material = {
            "target_kind": target_kind, "target_id": target_id, "source": source,
            "reason": reason, "issued_at": issued_at,
            "effective_from": effective_from, "effective_until": effective_until,
        }
        identity = "rev-" + hashlib.sha256(b"maho-revocation-v1\0" + canonical_bytes(material)).hexdigest()
        return cls(identity, target_kind, target_id, source, reason, issued_at, effective_from, effective_until)


@dataclass(frozen=True)
class ArtifactUse:
    artifact_id: ArtifactID
    generation_id: GenerationID
    transaction_id: TransactionID
    present: bool
    activated: bool
    executed: bool
    gained_privilege: bool
    changed_persistence: bool
    affected_kernel: bool
    evidence_complete: bool = True

    def __post_init__(self) -> None:
        if (self.activated or self.executed or self.gained_privilege or self.changed_persistence or self.affected_kernel) and not self.present:
            raise ValueError("artifact effects require presence evidence")
        if self.gained_privilege and not self.executed:
            raise ValueError("privilege evidence requires execution evidence")


@dataclass(frozen=True)
class ExposureAssessment:
    artifact_present: bool
    artifact_activated: bool
    artifact_executed: bool
    artifact_gained_privilege: bool
    artifact_changed_persistence: bool
    artifact_affected_kernel: bool
    evidence_complete: bool

    @property
    def credential_exposure(self) -> str:
        if not self.evidence_complete:
            return "unresolved"
        if self.artifact_gained_privilege or self.artifact_changed_persistence or self.artifact_affected_kernel:
            return "possible"
        return "none_established"


@dataclass(frozen=True)
class RevocationAnalysis:
    revoked_artifact_ids: tuple[ArtifactID, ...]
    affected_transaction_ids: tuple[TransactionID, ...]
    first_affected_generation_id: GenerationID | None
    affected_generation_ids: tuple[GenerationID, ...]
    affected_kernel_generation_ids: tuple[KernelGenerationID, ...]
    generation_trust: Mapping[GenerationID, TrustState]
    exposure: ExposureAssessment
    history_complete: bool

    def normal_recovery_eligible(self, generation_id: GenerationID) -> bool:
        return self.generation_trust.get(generation_id) in {TrustState.VERIFIED, TrustState.REVALIDATED}

    def newest_independently_trusted_ancestor(
        self, graph: GenerationGraph, current: GenerationID,
    ) -> SystemGeneration | None:
        return next((item for item in graph.lineage(current) if self.normal_recovery_eligible(item.generation_id)), None)

    def refusal_reason(self, graph: GenerationGraph, current: GenerationID) -> str | None:
        if self.newest_independently_trusted_ancestor(graph, current) is not None:
            return None
        return "all_local_history_contaminated" if self.history_complete else "last_trusted_state_predates_local_history"


@dataclass(frozen=True)
class RecoveryImpactResult:
    system_integrity: str
    credential_exposure: str


def recovery_impact(
    analysis: RevocationAnalysis, *, selected_generation_id: GenerationID | None,
    restoration_verified: bool,
) -> RecoveryImpactResult:
    restored = bool(
        selected_generation_id is not None and restoration_verified
        and analysis.normal_recovery_eligible(selected_generation_id)
    )
    return RecoveryImpactResult(
        system_integrity="restored" if restored else "unresolved",
        credential_exposure=analysis.exposure.credential_exposure,
    )


def _artifact_revoked(
    artifact: ArtifactEvidence, revocations: Iterable[RevocationRecord],
) -> bool:
    for record in revocations:
        if record.target_kind == "ARTIFACT" and record.target_id == str(artifact.artifact_id):
            return True
        if record.target_kind != "SIGNING_AUTHORITY" or record.target_id != artifact.signing_authority:
            continue
        if record.effective_from and artifact.signed_at < record.effective_from:
            continue
        if record.effective_until and artifact.signed_at > record.effective_until:
            continue
        return True
    return False


def _descendants(graph: GenerationGraph, seeds: set[GenerationID]) -> set[GenerationID]:
    return {
        generation_id for generation_id in graph.generations
        if any(item.generation_id in seeds for item in graph.lineage(generation_id))
    }


def _kernel_descendants(
    graph: KernelGenerationGraph, seeds: set[KernelGenerationID],
) -> set[KernelGenerationID]:
    return {
        generation_id for generation_id in graph.generations
        if any(item.kernel_generation_id in seeds for item in graph.lineage(generation_id))
    }


def _apply_kernel_revalidation_boundaries(
    graph: KernelGenerationGraph, affected: set[KernelGenerationID],
    seeds: set[KernelGenerationID],
) -> set[KernelGenerationID]:
    result: set[KernelGenerationID] = set()
    for generation_id in affected:
        lineage = graph.lineage(generation_id)
        nearest_seed = next((index for index, item in enumerate(lineage) if item.kernel_generation_id in seeds), None)
        nearest_revalidation = next((index for index, item in enumerate(lineage) if item.trust_state is TrustState.REVALIDATED), None)
        if nearest_revalidation is not None and nearest_seed is not None and nearest_revalidation < nearest_seed:
            continue
        result.add(generation_id)
    return result


def _apply_revalidation_boundaries(
    graph: GenerationGraph, affected: set[GenerationID], seeds: set[GenerationID],
) -> set[GenerationID]:
    result: set[GenerationID] = set()
    for generation_id in affected:
        lineage = graph.lineage(generation_id)
        nearest_seed = next((index for index, item in enumerate(lineage) if item.generation_id in seeds), None)
        nearest_revalidation = next((index for index, item in enumerate(lineage) if item.trust_state is TrustState.REVALIDATED), None)
        if nearest_revalidation is not None and nearest_seed is not None and nearest_revalidation < nearest_seed:
            continue
        result.add(generation_id)
    return result


def analyze_revocations(
    *, revocations: Iterable[RevocationRecord], artifacts: Iterable[ArtifactEvidence],
    uses: Iterable[ArtifactUse], system_graph: GenerationGraph,
    kernel_graph: KernelGenerationGraph, history_complete: bool,
) -> RevocationAnalysis:
    records = tuple(revocations)
    artifact_rows = tuple(artifacts)
    artifact_index = {item.artifact_id: item for item in artifact_rows}
    if len(artifact_index) != len(artifact_rows):
        raise ValueError("artifact revocation evidence identities must be unique")
    revoked = {item.artifact_id for item in artifact_rows if _artifact_revoked(item, records)}
    transactions = {item.transaction_id for item in artifact_rows if item.artifact_id in revoked}

    kernel_seeds = {
        item.kernel_generation_id for item in kernel_graph.generations.values()
        if any(artifact_id in revoked for artifact_id in item.artifact_ids)
    }
    affected_kernels = _apply_kernel_revalidation_boundaries(
        kernel_graph, _kernel_descendants(kernel_graph, kernel_seeds), kernel_seeds,
    )

    system_seeds: set[GenerationID] = set()
    for item in system_graph.generations.values():
        if any(artifact_id in revoked for artifact_id in item.artifact_ids):
            system_seeds.add(item.generation_id)
        if item.kernel_generation_id in affected_kernels:
            system_seeds.add(item.generation_id)
    use_rows = tuple(item for item in uses if item.artifact_id in revoked)
    for item in use_rows:
        if item.generation_id not in system_graph.generations:
            raise ValueError("artifact use references an unavailable generation")
        evidence = artifact_index.get(item.artifact_id)
        if evidence is None or evidence.transaction_id != item.transaction_id:
            raise ValueError("artifact use transaction contradicts provenance")
    system_seeds.update(item.generation_id for item in use_rows)
    affected_systems = _apply_revalidation_boundaries(
        system_graph, _descendants(system_graph, system_seeds), system_seeds,
    )

    trust: dict[GenerationID, TrustState] = {}
    for generation_id, item in system_graph.generations.items():
        if generation_id in affected_systems:
            trust[generation_id] = TrustState.CONTAMINATED
        elif item.trust_state is TrustState.REVALIDATED:
            trust[generation_id] = TrustState.REVALIDATED
        else:
            trust[generation_id] = system_graph.effective_trust(generation_id)

    first = min(
        system_seeds,
        key=lambda item: (len(system_graph.lineage(item)), str(item)),
        default=None,
    )
    exposure = ExposureAssessment(
        artifact_present=any(item.present for item in use_rows),
        artifact_activated=any(item.activated for item in use_rows),
        artifact_executed=any(item.executed for item in use_rows),
        artifact_gained_privilege=any(item.gained_privilege for item in use_rows),
        artifact_changed_persistence=any(item.changed_persistence for item in use_rows),
        artifact_affected_kernel=any(item.affected_kernel for item in use_rows) or bool(kernel_seeds),
        evidence_complete=bool(use_rows) and all(item.evidence_complete for item in use_rows),
    )
    return RevocationAnalysis(
        revoked_artifact_ids=tuple(sorted(revoked)),
        affected_transaction_ids=tuple(sorted(transactions)),
        first_affected_generation_id=first,
        affected_generation_ids=tuple(sorted(affected_systems)),
        affected_kernel_generation_ids=tuple(sorted(affected_kernels)),
        generation_trust=trust, exposure=exposure, history_complete=history_complete,
    )
