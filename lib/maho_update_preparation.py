#!/usr/bin/env python3
"""Preparation planner and fail-closed recovery gate for Maho Update."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from maho_update_staging import validate_manifest
from maho_update_state import UpdateState, transition_transaction, validate_transaction


@dataclass(frozen=True)
class PreparationEvidence:
    coherent_full_upgrade: bool
    required_disk_bytes: int
    available_disk_bytes: int
    power_status_known: bool
    power_policy_satisfied: bool
    concurrent_package_or_build_operation: bool
    maho_runtime_relationship_known: bool
    primary_kernel_relationship_known: bool
    fallback_kernel_relationship_known: bool
    headers_relationship_known: bool
    nvidia_dkms_relationship_known: bool
    boot_initramfs_relationship_known: bool
    recovery_protection_available: bool
    recovery_generation_id: str | None
    native_l3_certified: bool
    execution_environment: str = "production"


@dataclass(frozen=True)
class PreparationPlan:
    transaction_id: str
    package_generation_id: str
    complete: bool
    blockers: tuple[str, ...]
    activation_requirements: tuple[str, ...]
    recovery_generation_id: str | None
    requires_native_l3: bool
    execution_environment: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PreparationResult:
    transaction: dict[str, Any]
    plan: PreparationPlan


def plan_preparation(
    transaction: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cache_root: str | Path,
    evidence: PreparationEvidence,
) -> PreparationPlan:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.STAGED.value:
        raise ValueError("only a STAGED transaction may be prepared")
    validate_manifest(manifest, current, Path(cache_root))
    if evidence.execution_environment not in {"production", "fixture"}:
        raise ValueError("preparation execution environment is invalid")
    if evidence.native_l3_certified and current["recovery"]["native_l3_certified"] is not True:
        raise ValueError("preparation evidence cannot forge native L3 certification")
    if evidence.recovery_generation_id is not None and not evidence.recovery_generation_id.startswith("g3-"):
        raise ValueError("preparation recovery generation identity is invalid")

    blockers: list[str] = []
    if not evidence.coherent_full_upgrade:
        blockers.append("partial_upgrade_or_incoherent_package_set")
    if evidence.required_disk_bytes < 0 or evidence.available_disk_bytes < evidence.required_disk_bytes:
        blockers.append("insufficient_install_space")
    if not evidence.power_status_known:
        blockers.append("power_status_unknown")
    elif not evidence.power_policy_satisfied:
        blockers.append("power_policy_unsatisfied")
    if evidence.concurrent_package_or_build_operation:
        blockers.append("concurrent_package_or_build_operation")
    relationships = {
        "maho_runtime_relationship_unknown": evidence.maho_runtime_relationship_known,
        "primary_kernel_relationship_unknown": evidence.primary_kernel_relationship_known,
        "fallback_kernel_relationship_unknown": evidence.fallback_kernel_relationship_known,
        "headers_relationship_unknown": evidence.headers_relationship_known,
        "nvidia_dkms_relationship_unknown": evidence.nvidia_dkms_relationship_known,
        "boot_initramfs_relationship_unknown": evidence.boot_initramfs_relationship_known,
    }
    blockers.extend(name for name, known in relationships.items() if not known)
    if not evidence.recovery_protection_available:
        blockers.append("recovery_protection_unavailable")
    if evidence.recovery_generation_id is None:
        blockers.append("recovery_generation_unbound")
    elif current["recovery"]["generation_id"] not in {None, evidence.recovery_generation_id}:
        blockers.append("recovery_generation_mismatch")

    requires_native_l3 = bool(current["package_generation"]["packages"])
    if requires_native_l3 and evidence.execution_environment == "production" and not evidence.native_l3_certified:
        blockers.append("native_l3_certification_required")
    return PreparationPlan(
        transaction_id=current["transaction_id"],
        package_generation_id=current["package_generation"]["id"],
        complete=not blockers,
        blockers=tuple(blockers),
        activation_requirements=tuple(current["activation"]["requirements"]),
        recovery_generation_id=evidence.recovery_generation_id,
        requires_native_l3=requires_native_l3,
        execution_environment=evidence.execution_environment,
    )


def prepare_transaction(
    transaction: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cache_root: str | Path,
    evidence: PreparationEvidence,
    *,
    now=None,
) -> PreparationResult:
    plan = plan_preparation(transaction, manifest, cache_root, evidence)
    current = validate_transaction(transaction)
    if not plan.complete:
        blocked = transition_transaction(
            current, UpdateState.BLOCKED,
            reason="update preparation failed closed",
            blockers=list(plan.blockers),
            evidence={"preparation_plan": plan.as_dict()}, now=now,
        )
        return PreparationResult(blocked, plan)
    prepared = transition_transaction(
        current, UpdateState.PREPARED,
        reason="coherent update and recovery plan prepared",
        evidence={"preparation_plan": plan.as_dict()}, now=now,
    )
    return PreparationResult(prepared, plan)
