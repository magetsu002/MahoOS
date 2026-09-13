#!/usr/bin/env python3
"""Deterministic revocation-to-recovery orchestration for Guardian.

This module selects an exact recovery state; it never performs recovery and it
never emits shell commands.  Selection is bounded to the current generation
lineages and requires independently verified compatibility and artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping

from guardian_recovery_r3 import recovery_operations
from guardian_revocation import ExposureAssessment, RevocationAnalysis
from maho_generation_v2 import GenerationGraph, SystemGeneration
from maho_kernel_generation import (
    CompatibilityEvidence, KernelGeneration, KernelGenerationGraph,
    verify_artifacts,
)
from maho_trust_identity import (
    ArtifactID, GenerationID, KernelGenerationID, TransactionID, TrustState,
    canonical_bytes,
)


_TRUSTED = {TrustState.VERIFIED, TrustState.REVALIDATED}
_BOUNDED_SNAPSHOT = re.compile(r"btrfs:@snapshots/[1-9][0-9]*/snapshot")


@dataclass(frozen=True)
class RevocationRecoveryPlan:
    outcome: str
    mode: str
    incident_id: str
    reasons: tuple[str, ...]
    current_system_generation_id: GenerationID
    current_kernel_generation_id: KernelGenerationID
    target_system_generation_id: GenerationID | None
    target_kernel_generation_id: KernelGenerationID | None
    revoked_artifact_ids: tuple[ArtifactID, ...]
    affected_transaction_ids: tuple[TransactionID, ...]
    affected_generation_ids: tuple[GenerationID, ...]
    affected_kernel_generation_ids: tuple[KernelGenerationID, ...]
    exposure: ExposureAssessment
    operations: tuple[str, ...]
    evidence_digest: ArtifactID
    requires_explicit_authorization: bool = True
    source_only: bool = True

    @property
    def ready(self) -> bool:
        return self.outcome == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "kind": "guardian-revocation-recovery-plan",
            "outcome": self.outcome,
            "mode": self.mode,
            "incident_id": self.incident_id,
            "reasons": list(self.reasons),
            "current_system_generation_id": str(self.current_system_generation_id),
            "current_kernel_generation_id": str(self.current_kernel_generation_id),
            "target_system_generation_id": str(self.target_system_generation_id) if self.target_system_generation_id else None,
            "target_kernel_generation_id": str(self.target_kernel_generation_id) if self.target_kernel_generation_id else None,
            "revoked_artifact_ids": [str(item) for item in self.revoked_artifact_ids],
            "affected_transaction_ids": [str(item) for item in self.affected_transaction_ids],
            "affected_generation_ids": [str(item) for item in self.affected_generation_ids],
            "affected_kernel_generation_ids": [str(item) for item in self.affected_kernel_generation_ids],
            "exposure": {
                "artifact_present": self.exposure.artifact_present,
                "artifact_activated": self.exposure.artifact_activated,
                "artifact_executed": self.exposure.artifact_executed,
                "artifact_gained_privilege": self.exposure.artifact_gained_privilege,
                "artifact_changed_persistence": self.exposure.artifact_changed_persistence,
                "artifact_affected_kernel": self.exposure.artifact_affected_kernel,
                "evidence_complete": self.exposure.evidence_complete,
                "credential_exposure": self.exposure.credential_exposure,
            },
            "operations": list(self.operations),
            "evidence_digest": str(self.evidence_digest),
            "requires_explicit_authorization": self.requires_explicit_authorization,
            "source_only": self.source_only,
        }


def _analysis_material(analysis: RevocationAnalysis) -> dict[str, Any]:
    return {
        "revoked_artifact_ids": [str(item) for item in analysis.revoked_artifact_ids],
        "affected_transaction_ids": [str(item) for item in analysis.affected_transaction_ids],
        "directly_affected_generation_ids": [str(item) for item in analysis.directly_affected_generation_ids],
        "kernel_induced_generation_ids": [str(item) for item in analysis.kernel_induced_generation_ids],
        "affected_generation_ids": [str(item) for item in analysis.affected_generation_ids],
        "affected_kernel_generation_ids": [str(item) for item in analysis.affected_kernel_generation_ids],
        "generation_trust": {
            str(key): value.value for key, value in sorted(analysis.generation_trust.items())
        },
        "history_complete": analysis.history_complete,
        "exposure": {
            "artifact_present": analysis.exposure.artifact_present,
            "artifact_activated": analysis.exposure.artifact_activated,
            "artifact_executed": analysis.exposure.artifact_executed,
            "artifact_gained_privilege": analysis.exposure.artifact_gained_privilege,
            "artifact_changed_persistence": analysis.exposure.artifact_changed_persistence,
            "artifact_affected_kernel": analysis.exposure.artifact_affected_kernel,
            "evidence_complete": analysis.exposure.evidence_complete,
        },
    }


def _selection_evidence_digest(
    analysis: RevocationAnalysis,
    *, mode: str, current_system: GenerationID, current_kernel: KernelGenerationID,
    target_system: GenerationID, target_kernel: KernelGeneration,
    compatibility: CompatibilityEvidence,
) -> ArtifactID:
    material = {
        "analysis": _analysis_material(analysis),
        "mode": mode,
        "current_system_generation_id": str(current_system),
        "current_kernel_generation_id": str(current_kernel),
        "target_system_generation_id": str(target_system),
        "target_kernel_generation_id": str(target_kernel.kernel_generation_id),
        "target_kernel_artifact_ids": [str(item) for item in target_kernel.artifact_ids],
        "compatibility": {
            "system_generation_id": str(compatibility.system_generation_id),
            "kernel_generation_id": str(compatibility.kernel_generation_id),
            "root_manifest_sha256": compatibility.root_manifest_sha256,
            "filesystem_identity": compatibility.filesystem_identity.lower(),
            "kernel_abi": compatibility.kernel_abi,
            "modules_abi": compatibility.modules_abi,
            "verifier_identity": compatibility.verifier_identity,
            "independently_verified": compatibility.independently_verified,
        },
    }
    return ArtifactID.from_content(canonical_bytes(material))


def _compatibility_ok(
    system: SystemGeneration,
    kernel: KernelGeneration,
    evidence: CompatibilityEvidence | None,
) -> bool:
    if evidence is None or not evidence.independently_verified or not evidence.verifier_identity:
        return False
    if system.root_identity is None:
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


def _artifacts_ok(
    kernel: KernelGeneration,
    observed: Mapping[KernelGenerationID, Mapping[ArtifactID, bytes]],
) -> bool:
    values = observed.get(kernel.kernel_generation_id)
    if values is None:
        return False
    valid, _ = verify_artifacts(kernel, values)
    return valid


def _refusal(
    *, incident_id: str, reason: str, analysis: RevocationAnalysis,
    current_system: GenerationID, current_kernel: KernelGenerationID,
    digest: ArtifactID,
) -> RevocationRecoveryPlan:
    return RevocationRecoveryPlan(
        outcome="REFUSE",
        mode="EXTERNAL_RECOVERY",
        incident_id=incident_id,
        reasons=(reason,),
        current_system_generation_id=current_system,
        current_kernel_generation_id=current_kernel,
        target_system_generation_id=None,
        target_kernel_generation_id=None,
        revoked_artifact_ids=analysis.revoked_artifact_ids,
        affected_transaction_ids=analysis.affected_transaction_ids,
        affected_generation_ids=analysis.affected_generation_ids,
        affected_kernel_generation_ids=analysis.affected_kernel_generation_ids,
        exposure=analysis.exposure,
        operations=(),
        evidence_digest=digest,
    )


def _ready(
    *, incident_id: str, mode: str, analysis: RevocationAnalysis,
    current_system: GenerationID, current_kernel: KernelGenerationID,
    target_system: GenerationID, target_kernel: KernelGenerationID,
    digest: ArtifactID,
) -> RevocationRecoveryPlan:
    reasons = ["newest_independently_trusted_recovery_state_selected"]
    if analysis.exposure.credential_exposure != "none_established":
        reasons.append(f"credential_exposure_{analysis.exposure.credential_exposure}")
    return RevocationRecoveryPlan(
        outcome="READY",
        mode=mode,
        incident_id=incident_id,
        reasons=tuple(reasons),
        current_system_generation_id=current_system,
        current_kernel_generation_id=current_kernel,
        target_system_generation_id=target_system,
        target_kernel_generation_id=target_kernel,
        revoked_artifact_ids=analysis.revoked_artifact_ids,
        affected_transaction_ids=analysis.affected_transaction_ids,
        affected_generation_ids=analysis.affected_generation_ids,
        affected_kernel_generation_ids=analysis.affected_kernel_generation_ids,
        exposure=analysis.exposure,
        operations=recovery_operations(mode),
        evidence_digest=digest,
    )


def plan_revocation_recovery(
    analysis: RevocationAnalysis,
    *,
    incident_id: str,
    current_system_generation_id: GenerationID,
    current_kernel_generation_id: KernelGenerationID,
    system_graph: GenerationGraph,
    kernel_graph: KernelGenerationGraph,
    compatibility: Mapping[tuple[GenerationID, KernelGenerationID], CompatibilityEvidence],
    observed_kernel_artifacts: Mapping[KernelGenerationID, Mapping[ArtifactID, bytes]],
) -> RevocationRecoveryPlan:
    """Select the smallest independently trusted recovery state, or refuse."""
    if not incident_id:
        raise ValueError("incident identity is required")
    if current_system_generation_id not in system_graph.generations:
        raise ValueError("current SystemGeneration is unavailable")
    if current_kernel_generation_id not in kernel_graph.generations:
        raise ValueError("current KernelGeneration is unavailable")
    current_system = system_graph.generations[current_system_generation_id]
    if current_system.kernel_generation_id != current_kernel_generation_id:
        raise ValueError("current generation pair is inconsistent")
    system_ids = set(system_graph.generations)
    kernel_ids = set(kernel_graph.generations)
    affected_systems = set(analysis.affected_generation_ids)
    affected_kernels = set(analysis.affected_kernel_generation_ids)
    directly_affected = set(analysis.directly_affected_generation_ids)
    kernel_induced = set(analysis.kernel_induced_generation_ids)
    if set(analysis.generation_trust) != system_ids:
        raise ValueError("revocation analysis does not bind exact SystemGeneration graph")
    if not affected_systems <= system_ids or not affected_kernels <= kernel_ids:
        raise ValueError("revocation analysis references unavailable generations")
    if directly_affected & kernel_induced or directly_affected | kernel_induced != affected_systems:
        raise ValueError("revocation contamination partition is inconsistent")
    evidence_digest = ArtifactID.from_content(canonical_bytes(_analysis_material(analysis)))

    if not analysis.revoked_artifact_ids:
        return _refusal(
            incident_id=incident_id, reason="revoked_artifact_evidence_unavailable",
            analysis=analysis, current_system=current_system_generation_id,
            current_kernel=current_kernel_generation_id, digest=evidence_digest,
        )
    if current_system_generation_id not in affected_systems and current_kernel_generation_id not in affected_kernels:
        return _refusal(
            incident_id=incident_id, reason="current_generation_not_affected",
            analysis=analysis, current_system=current_system_generation_id,
            current_kernel=current_kernel_generation_id, digest=evidence_digest,
        )

    if current_system_generation_id not in directly_affected and current_kernel_generation_id in affected_kernels:
        for kernel in kernel_graph.lineage(current_kernel_generation_id)[1:]:
            kernel_id = kernel.kernel_generation_id
            if kernel_id in affected_kernels or kernel_graph.effective_trust(kernel_id) not in _TRUSTED:
                continue
            if not _compatibility_ok(current_system, kernel, compatibility.get((current_system_generation_id, kernel_id))):
                continue
            if not _artifacts_ok(kernel, observed_kernel_artifacts):
                continue
            return _ready(
                incident_id=incident_id, mode="KERNEL_ONLY", analysis=analysis,
                current_system=current_system_generation_id, current_kernel=current_kernel_generation_id,
                target_system=current_system_generation_id, target_kernel=kernel_id,
                digest=_selection_evidence_digest(
                    analysis, mode="KERNEL_ONLY",
                    current_system=current_system_generation_id,
                    current_kernel=current_kernel_generation_id,
                    target_system=current_system_generation_id,
                    target_kernel=kernel,
                    compatibility=compatibility[(current_system_generation_id, kernel_id)],
                ),
            )

    for system in system_graph.lineage(current_system_generation_id)[1:]:
        system_id = system.generation_id
        kernel_id = system.kernel_generation_id
        if system_id in affected_systems or analysis.generation_trust.get(system_id) not in _TRUSTED:
            continue
        if system.root_identity is None or _BOUNDED_SNAPSHOT.fullmatch(system.root_identity.snapshot_identity) is None:
            continue
        if kernel_id is None or kernel_id not in kernel_graph.generations or kernel_id in affected_kernels:
            continue
        kernel = kernel_graph.generations[kernel_id]
        if kernel_graph.effective_trust(kernel_id) not in _TRUSTED:
            continue
        if not _compatibility_ok(system, kernel, compatibility.get((system_id, kernel_id))):
            continue
        if not _artifacts_ok(kernel, observed_kernel_artifacts):
            continue
        return _ready(
            incident_id=incident_id, mode="FULL_GENERATION", analysis=analysis,
            current_system=current_system_generation_id, current_kernel=current_kernel_generation_id,
            target_system=system_id, target_kernel=kernel_id,
            digest=_selection_evidence_digest(
                analysis, mode="FULL_GENERATION",
                current_system=current_system_generation_id,
                current_kernel=current_kernel_generation_id,
                target_system=system_id,
                target_kernel=kernel,
                compatibility=compatibility[(system_id, kernel_id)],
            ),
        )

    reason = analysis.refusal_reason(system_graph, current_system_generation_id)
    if reason is None:
        reason = "no_independently_verified_compatible_recovery_state"
    return _refusal(
        incident_id=incident_id, reason=reason,
        analysis=analysis, current_system=current_system_generation_id,
        current_kernel=current_kernel_generation_id, digest=evidence_digest,
    )
