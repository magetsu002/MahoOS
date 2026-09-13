#!/usr/bin/env python3
"""Source-only R3 planner for bounded native generation recovery."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from guardian_offline_recovery import DirectoryRecoveryProvider
from maho_generation_v2 import GenerationGraph, SystemGeneration
from maho_kernel_generation import KernelGenerationGraph, can_boot, verify_artifacts
from maho_trust_identity import GenerationID, KernelGenerationID, TrustState, canonical_json

_R2_CAMPAIGN = re.compile(r"r2-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}")
_SNAPSHOT = re.compile(r"btrfs:@snapshots/([1-9][0-9]*)/snapshot")
_TRUSTED = {TrustState.VERIFIED, TrustState.REVALIDATED}


class R3PlanningError(ValueError):
    pass


@dataclass(frozen=True)
class R3RecoveryIntent:
    mode: str
    incident_id: str
    r2_campaign_id: str
    current_system_generation_id: GenerationID
    current_kernel_generation_id: KernelGenerationID
    target_system_generation_id: GenerationID
    target_kernel_generation_id: KernelGenerationID
    target_snapshot_identity: str
    target_snapshot_id: int | None
    operations: tuple[str, ...]
    requires_offline_recovery: bool = True
    mutates_live_root: bool = False
    preserves_home: bool = True
    requires_user_reboot: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "incident_id": self.incident_id,
            "r2_campaign_id": self.r2_campaign_id,
            "current_system_generation_id": str(self.current_system_generation_id),
            "current_kernel_generation_id": str(self.current_kernel_generation_id),
            "target_system_generation_id": str(self.target_system_generation_id),
            "target_kernel_generation_id": str(self.target_kernel_generation_id),
            "target_snapshot_identity": self.target_snapshot_identity,
            "target_snapshot_id": self.target_snapshot_id,
            "operations": list(self.operations),
            "requires_offline_recovery": self.requires_offline_recovery,
            "mutates_live_root": self.mutates_live_root,
            "preserves_home": self.preserves_home,
            "requires_user_reboot": self.requires_user_reboot,
        }
    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())

    @property
    def intent_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _require_r2_report(report: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]]:
    if report.get("schema_version") != 2:
        raise R3PlanningError("r2_report_schema_invalid")
    if report.get("outcome") != "PASS":
        raise R3PlanningError("r2_not_certified_pass")
    if report.get("reason") != "independently_trusted_generation_pair_selected":
        raise R3PlanningError("r2_reason_invalid")
    campaign = report.get("campaign_id")
    if not isinstance(campaign, str) or _R2_CAMPAIGN.fullmatch(campaign) is None:
        raise R3PlanningError("r2_campaign_invalid")
    selection = report.get("selection")
    if not isinstance(selection, Mapping):
        raise R3PlanningError("r2_selection_missing")
    if selection.get("outcome") != "READY" or selection.get("selection_matches_expected") is not True:
        raise R3PlanningError("r2_selection_not_ready")
    if selection.get("source_only") is not True or selection.get("requires_reboot") is not True:
        raise R3PlanningError("r2_selection_contract_invalid")
    return campaign, selection

def _selected_ids(selection: Mapping[str, Any]) -> tuple[GenerationID, KernelGenerationID]:
    target_system = selection.get("target_system_generation_id")
    target_kernel = selection.get("target_kernel_generation_id")
    expected_system = selection.get("expected_system_generation_id")
    expected_kernel = selection.get("expected_kernel_generation_id")
    if not all(isinstance(v, str) and v for v in (target_system, target_kernel, expected_system, expected_kernel)):
        raise R3PlanningError("r2_selected_identity_missing")
    if target_system != expected_system or target_kernel != expected_kernel:
        raise R3PlanningError("r2_selected_identity_mismatch")
    return GenerationID(target_system), KernelGenerationID(target_kernel)


def _target_snapshot(system: SystemGeneration) -> tuple[str, int | None]:
    if system.root_identity is None:
        raise R3PlanningError("target_root_identity_missing")
    identity = system.root_identity.snapshot_identity
    match = _SNAPSHOT.fullmatch(identity)
    if match is None:
        return identity, None
    return identity, int(match.group(1))


def recovery_operations(mode: str) -> tuple[str, ...]:
    if mode == "KERNEL_ONLY":
        return (
            "preserve-incident-evidence",
            "verify-selected-generation-again",
            "stage-exact-selected-kernel-artifacts",
            "verify-boot-artifacts-and-current-root-identity",
            "request-reboot",
            "verify-postboot-kernel-and-home-identity",
        )
    if mode != "FULL_GENERATION":
        raise ValueError("unknown recovery mode")
    return (
        "preserve-incident-evidence",
        "verify-selected-generation-again",
        "create-read-only-emergency-backup",
        "restore-exact-selected-btrfs-generation",
        "stage-exact-selected-kernel-artifacts",
        "verify-restored-root-and-boot-artifacts",
        "request-reboot",
        "verify-postboot-generation-and-home-identity",
    )


def plan_r3_recovery(
    report: Mapping[str, Any], evidence_root: str | Path, *,
    current_system_generation_id: GenerationID,
    current_kernel_generation_id: KernelGenerationID,
) -> R3RecoveryIntent:
    campaign, selection = _require_r2_report(report)
    selected_system_id, selected_kernel_id = _selected_ids(selection)
    provider = DirectoryRecoveryProvider(evidence_root)
    systems = provider.system_generations()
    kernels = provider.kernel_generations()
    system_graph = GenerationGraph(systems)
    kernel_graph = KernelGenerationGraph(kernels)
    if current_system_generation_id not in system_graph.generations:
        raise R3PlanningError("current_system_generation_missing")
    if current_kernel_generation_id not in kernel_graph.generations:
        raise R3PlanningError("current_kernel_generation_missing")
    if selected_system_id not in system_graph.generations:
        raise R3PlanningError("selected_system_generation_missing")
    if selected_kernel_id not in kernel_graph.generations:
        raise R3PlanningError("selected_kernel_generation_missing")
    selected_system = system_graph.generations[selected_system_id]
    selected_kernel = kernel_graph.generations[selected_kernel_id]
    if system_graph.effective_trust(selected_system_id) not in _TRUSTED:
        raise R3PlanningError("selected_system_not_trusted")
    if kernel_graph.effective_trust(selected_kernel_id) not in _TRUSTED:
        raise R3PlanningError("selected_kernel_not_trusted")
    if selected_system.kernel_generation_id != selected_kernel_id:
        raise R3PlanningError("selected_pair_manifest_mismatch")
    compatibility = provider.compatibility().get((selected_system_id, selected_kernel_id))
    if not can_boot(selected_kernel, selected_system, compatibility):
        raise R3PlanningError("selected_pair_not_independently_compatible")
    artifacts_ok, reasons = verify_artifacts(
        selected_kernel, provider.observed_kernel_artifacts(selected_kernel)
    )
    if not artifacts_ok:
        raise R3PlanningError("selected_kernel_artifacts_invalid:" + ",".join(reasons))
    if selected_kernel_id == current_kernel_generation_id and selected_system_id == current_system_generation_id:
        raise R3PlanningError("recovery_not_required")
    lineage_ids = {item.generation_id for item in system_graph.lineage(current_system_generation_id)}
    if selected_system_id not in lineage_ids:
        raise R3PlanningError("selected_system_not_in_current_lineage")
    snapshot_identity, snapshot_id = _target_snapshot(selected_system)
    incident_id = selection.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise R3PlanningError("incident_identity_missing")
    if selected_system_id == current_system_generation_id:
        mode = "KERNEL_ONLY"
        operations = recovery_operations(mode)
    else:
        if snapshot_id is None:
            raise R3PlanningError("full_recovery_target_is_not_bounded_btrfs_snapshot")
        mode = "FULL_GENERATION"
        operations = recovery_operations(mode)
    return R3RecoveryIntent(
        mode=mode,
        incident_id=incident_id,
        r2_campaign_id=campaign,
        current_system_generation_id=current_system_generation_id,
        current_kernel_generation_id=current_kernel_generation_id,
        target_system_generation_id=selected_system_id,
        target_kernel_generation_id=selected_kernel_id,
        target_snapshot_identity=snapshot_identity,
        target_snapshot_id=snapshot_id,
        operations=operations,
    )


def intent_envelope(intent: R3RecoveryIntent) -> dict[str, Any]:
    """Stable one-time authority material for a later privileged executor."""
    return {
        "schema_version": 1,
        "intent": intent.as_dict(),
        "intent_sha256": intent.intent_sha256,
        "authority_scope": "guardian-r3-bounded-generation-recovery",
        "automatic": False,
        "requires_explicit_user_authorization": True,
    }
