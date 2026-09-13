#!/usr/bin/env python3
"""Source-only contract for an independent Guardian Recovery environment.

This module plans; it contains no boot, mount, restore, package, or reboot
executor.  Provider evidence is read from an offline root and every ambiguous
condition becomes an explicit external-recovery refusal.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

from maho_generation_v2 import GenerationGraph, SystemGeneration
from maho_kernel_generation import (
    CompatibilityEvidence, ContentAddressedArtifactStore, KernelGeneration,
    KernelGenerationGraph, newest_verified_pair, verify_artifacts,
)
from maho_trust_identity import GenerationID, KernelGenerationID, TrustState, parse_trust_state


@dataclass(frozen=True)
class RecoveryEnvironmentEvidence:
    environment_id: str
    trust_state: TrustState
    manifest_verified: bool
    verification_authority: str
    verification_kernel_id: str
    revocation_metadata_fresh: bool

    def validate(self, suspected_running_kernel_id: KernelGenerationID) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.trust_state not in {TrustState.VERIFIED, TrustState.REVALIDATED}:
            reasons.append("recovery_environment_untrusted")
        if not self.manifest_verified:
            reasons.append("recovery_environment_manifest_unverified")
        if not self.verification_authority or self.verification_authority == self.environment_id:
            reasons.append("recovery_environment_self_certified")
        if self.verification_kernel_id == str(suspected_running_kernel_id):
            reasons.append("suspected_kernel_cannot_certify_itself")
        if not self.revocation_metadata_fresh:
            reasons.append("revocation_metadata_stale")
        return tuple(reasons)


class RecoveryProvider(Protocol):
    provider_id: str

    def system_generations(self) -> tuple[SystemGeneration, ...]: ...
    def kernel_generations(self) -> tuple[KernelGeneration, ...]: ...
    def compatibility(self) -> Mapping[tuple[GenerationID, KernelGenerationID], CompatibilityEvidence]: ...
    def observed_kernel_artifacts(self, generation: KernelGeneration) -> Mapping[Any, bytes]: ...


class DirectoryRecoveryProvider:
    """Read-only manifest provider for an offline-root-shaped directory."""
    provider_id = "guardian-offline-directory-v1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.store = ContentAddressedArtifactStore(self.root / "artifacts")

    def _json_files(self, relative: str) -> list[Mapping[str, Any]]:
        directory = self.root / relative
        values: list[Mapping[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, Mapping):
                raise ValueError(f"manifest is not an object: {path.name}")
            values.append(data)
        return values

    def system_generations(self) -> tuple[SystemGeneration, ...]:
        return tuple(SystemGeneration.parse(item) for item in self._json_files("manifests/system"))

    def kernel_generations(self) -> tuple[KernelGeneration, ...]:
        return tuple(KernelGeneration.parse(item) for item in self._json_files("manifests/kernel"))

    def compatibility(self) -> Mapping[tuple[GenerationID, KernelGenerationID], CompatibilityEvidence]:
        result: dict[tuple[GenerationID, KernelGenerationID], CompatibilityEvidence] = {}
        for item in self._json_files("evidence/compatibility"):
            evidence = CompatibilityEvidence(
                system_generation_id=GenerationID(item["system_generation_id"]),
                kernel_generation_id=KernelGenerationID(item["kernel_generation_id"]),
                root_manifest_sha256=item["root_manifest_sha256"],
                filesystem_identity=item["filesystem_identity"],
                kernel_abi=item["kernel_abi"], modules_abi=item["modules_abi"],
                verifier_identity=item["verifier_identity"],
                independently_verified=item["independently_verified"],
            )
            key = (evidence.system_generation_id, evidence.kernel_generation_id)
            if key in result:
                raise ValueError("duplicate compatibility evidence")
            result[key] = evidence
        return result

    def observed_kernel_artifacts(self, generation: KernelGeneration) -> Mapping[Any, bytes]:
        observed = {}
        for artifact_id in generation.artifact_ids:
            path = self.store.path_for(artifact_id)
            observed[artifact_id] = path.read_bytes()
        return observed


@dataclass(frozen=True)
class RecoveryPlan:
    outcome: str
    reasons: tuple[str, ...]
    provider_id: str
    incident_id: str
    target_system_generation_id: GenerationID | None = None
    target_kernel_generation_id: KernelGenerationID | None = None
    operations: tuple[str, ...] = ()
    source_only: bool = True
    requires_reboot: bool = False

    @property
    def eligible(self) -> bool:
        return self.outcome == "READY"

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome, "reasons": list(self.reasons),
            "provider_id": self.provider_id, "incident_id": self.incident_id,
            "target_system_generation_id": str(self.target_system_generation_id) if self.target_system_generation_id else None,
            "target_kernel_generation_id": str(self.target_kernel_generation_id) if self.target_kernel_generation_id else None,
            "operations": list(self.operations), "source_only": self.source_only,
            "requires_reboot": self.requires_reboot,
        }


def refusal(provider_id: str, incident_id: str, *reasons: str) -> RecoveryPlan:
    return RecoveryPlan(
        outcome="REFUSE_EXTERNAL_RECOVERY_REQUIRED", reasons=tuple(dict.fromkeys(reasons)),
        provider_id=provider_id, incident_id=incident_id,
    )


def plan_offline_recovery(
    provider: RecoveryProvider, environment: RecoveryEnvironmentEvidence, *,
    current_system_generation_id: GenerationID,
    suspected_running_kernel_id: KernelGenerationID,
    incident_id: str,
) -> RecoveryPlan:
    if not incident_id:
        return refusal(provider.provider_id, "unknown", "incident_identity_missing")
    environment_reasons = environment.validate(suspected_running_kernel_id)
    if environment_reasons:
        return refusal(provider.provider_id, incident_id, *environment_reasons)
    try:
        systems = provider.system_generations()
        kernels = provider.kernel_generations()
        if not systems or not kernels:
            return refusal(provider.provider_id, incident_id, "local_generation_history_unavailable")
        system_graph = GenerationGraph(systems)
        kernel_graph = KernelGenerationGraph(kernels)
        compatibility = provider.compatibility()
        pair = newest_verified_pair(current_system_generation_id, system_graph, kernel_graph, compatibility)
        if pair is None:
            return refusal(provider.provider_id, incident_id, "no_independently_trusted_compatible_pair")
        system, kernel = pair
        artifacts_ok, artifact_reasons = verify_artifacts(kernel, provider.observed_kernel_artifacts(kernel))
        if not artifacts_ok:
            return refusal(provider.provider_id, incident_id, "kernel_artifact_verification_failed", *artifact_reasons)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return refusal(provider.provider_id, incident_id, "provider_evidence_invalid", type(exc).__name__)
    return RecoveryPlan(
        outcome="READY", reasons=(), provider_id=provider.provider_id,
        incident_id=incident_id, target_system_generation_id=system.generation_id,
        target_kernel_generation_id=kernel.kernel_generation_id,
        operations=(
            "preserve-incident-evidence", "stage-bounded-generation-restore",
            "verify-staged-artifacts", "verify-postconditions", "request-reboot",
        ),
        source_only=True, requires_reboot=True,
    )
