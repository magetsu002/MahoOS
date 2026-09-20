#!/usr/bin/env python3
"""Normal-impact update preparation and fixture-certified lifecycle.

This lane deliberately has no production mutation authority yet. It proves that
repo/AUR provenance is orthogonal to exact artifact effects, and that a normal
package generation can complete discovery/staging/preparation independently of
M4B while production execution remains fail-closed until hardware certification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from maho_update_effects import aggregate_effects, validate_provenance
from maho_update_normal_authority import authorize_normal_plan, certification_confirmation
from maho_update_staging import validate_manifest
from maho_update_state import UpdateState, transition_transaction, validate_transaction


@dataclass(frozen=True)
class NormalPreparationEvidence:
    discovery_generation_current: bool
    coherent_independent_generation: bool
    required_disk_bytes: int
    available_disk_bytes: int
    power_status_known: bool
    power_policy_satisfied: bool
    concurrent_package_or_build_operation: bool
    candidate_root_available: bool
    guardian_admission_available: bool
    execution_environment: str = "production"


@dataclass(frozen=True)
class NormalExecutionPlan:
    transaction_id: str
    package_generation_id: str
    source_provenance_id: str
    payload_paths: tuple[str, ...]
    effects: tuple[str, ...]
    activation_requirements: tuple[str, ...]
    selection_kind: str
    execution_environment: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NormalPreparationResult:
    transaction: dict[str, Any]
    plan: NormalExecutionPlan
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class NormalExecutionResult:
    transaction: dict[str, Any]
    plan: NormalExecutionPlan
    mutation_started: bool


class NormalUpdateOps(Protocol):
    fixture_safe: bool
    production_safe: bool

    def install_candidate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]: ...
    def guardian_admit(self, plan: NormalExecutionPlan) -> Mapping[str, Any]: ...
    def activate(self, plan: NormalExecutionPlan) -> Mapping[str, Any]: ...
    def verify(self, plan: NormalExecutionPlan) -> Mapping[str, Any]: ...


def _require_ok(value: Mapping[str, Any], stage: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("ok") is not True:
        detail = json.dumps(dict(value), sort_keys=True, separators=(",", ":")) if isinstance(value, Mapping) else repr(value)
        if len(detail) > 3000:
            detail = detail[:3000] + "..."
        raise RuntimeError(f"normal update {stage} did not produce positive bounded evidence: {detail}")
    return dict(value)


def _provenance_map(transaction: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    current = validate_transaction(transaction)
    result: dict[str, dict[str, Any]] = {}
    for raw in current["source_provenance"]["packages"]:
        entry = dict(raw)
        name = str(entry.pop("name"))
        result[name] = validate_provenance(entry)
    return result


def _selection_is_coherent(selection: Mapping[str, Any]) -> bool:
    kind = selection.get("kind")
    proof = selection.get("solver_proof")
    if kind == "full":
        return isinstance(proof, Mapping) and proof.get("kind") == "full-system-solver"
    if not isinstance(proof, Mapping):
        return False
    if kind == "independent-normal":
        return (
            proof.get("kind") == "isolated-pacman-independent-generation"
            and proof.get("selected_versions_match_full") is True
            and proof.get("selected_repositories_match_full") is True
            and proof.get("production_ignore_execution") is False
            and sorted(proof.get("deferred_boot_packages", [])) == sorted(selection.get("deferred_boot_packages", []))
        )
    if kind == "coherent-subset":
        return (
            proof.get("kind") == "isolated-pacman-coherent-subset"
            and proof.get("selected_versions_match_full") is True
            and proof.get("selected_repositories_match_full") is True
            and proof.get("production_ignore_execution") is False
            and isinstance(proof.get("target_packages"), list)
            and bool(proof.get("target_packages"))
        )
    return False


def prepare_normal_transaction(
    transaction: Mapping[str, Any],
    manifest: Mapping[str, Any],
    cache_root: str | Path,
    evidence: NormalPreparationEvidence,
    *,
    now=None,
) -> NormalPreparationResult:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.STAGED.value:
        raise ValueError("normal preparation requires STAGED transaction")
    staged = validate_manifest(manifest, current, Path(cache_root))
    if staged.get("schema_version") != 2:
        raise ValueError("normal preparation requires exact staged effect evidence")
    if evidence.execution_environment not in {"production", "fixture"}:
        raise ValueError("normal execution environment is invalid")

    effects = aggregate_effects(staged["payloads"])
    provenance = _provenance_map(current)
    for payload in staged["payloads"]:
        name = payload["name"]
        observed = validate_provenance(payload["provenance"])
        if provenance.get(name) != observed:
            raise ValueError(f"staged artifact provenance drifted:{name}")

    blockers: list[str] = []
    if effects["classification"] != "normal":
        blockers.append("boot_critical_effects_detected")
        blockers.extend(f"boot_critical_package:{name}" for name in effects["boot_critical_packages"])
    if not evidence.discovery_generation_current:
        blockers.append("stale_update_transaction")
    if not evidence.coherent_independent_generation or not _selection_is_coherent(current["selection"]):
        blockers.append("independent_generation_not_proven")
    if evidence.required_disk_bytes < 0 or evidence.available_disk_bytes < evidence.required_disk_bytes:
        blockers.append("insufficient_install_space")
    if not evidence.power_status_known:
        blockers.append("power_status_unknown")
    elif not evidence.power_policy_satisfied:
        blockers.append("power_policy_unsatisfied")
    if evidence.concurrent_package_or_build_operation:
        blockers.append("concurrent_package_or_build_operation")
    if not evidence.candidate_root_available:
        blockers.append("candidate_root_unavailable")
    if not evidence.guardian_admission_available:
        blockers.append("guardian_admission_unavailable")

    plan = NormalExecutionPlan(
        transaction_id=current["transaction_id"],
        package_generation_id=current["package_generation"]["id"],
        source_provenance_id=current["source_provenance"]["id"],
        payload_paths=tuple(item["path"] for item in staged["payloads"]),
        effects=tuple(effects["effects"]),
        activation_requirements=tuple(effects["activation_requirements"]),
        selection_kind=current["selection"]["kind"],
        execution_environment=evidence.execution_environment,
    )
    if blockers:
        blocked = transition_transaction(
            current,
            UpdateState.BLOCKED,
            reason="normal update preparation failed closed",
            blockers=blockers,
            evidence={"normal_plan": plan.as_dict(), "effects": effects},
            now=now,
        )
        return NormalPreparationResult(blocked, plan, tuple(blockers))
    prepared = transition_transaction(
        current,
        UpdateState.PREPARED,
        reason="coherent non-boot generation prepared from exact artifacts",
        evidence={"normal_plan": plan.as_dict(), "effects": effects},
        now=now,
    )
    return NormalPreparationResult(prepared, plan, ())


def _execute_normal_lifecycle(
    current: Mapping[str, Any],
    plan: NormalExecutionPlan,
    ops: NormalUpdateOps,
    *,
    now=None,
) -> NormalExecutionResult:
    ready = transition_transaction(
        current,
        UpdateState.MAINTENANCE_READY,
        reason="normal update exact generation is ready for bounded execution",
        evidence={"normal_plan": plan.as_dict()},
        now=now,
    )
    installing = transition_transaction(
        ready,
        UpdateState.INSTALLING,
        reason="normal offline candidate installation started",
        now=now,
    )
    try:
        install = _require_ok(ops.install_candidate(plan), "candidate installation")
        admission = _require_ok(ops.guardian_admit(plan), "Guardian Admission")
    except Exception as exc:
        failed = transition_transaction(
            installing,
            UpdateState.ATTENTION_REQUIRED,
            reason="normal candidate preparation failed",
            blockers=["normal_candidate_preparation_failed"],
            evidence={"error": str(exc)},
            now=now,
        )
        return NormalExecutionResult(failed, plan, True)

    pending = transition_transaction(
        installing,
        UpdateState.INSTALLED_PENDING_ACTIVATION,
        reason="normal candidate installed and admitted; activation is explicit",
        evidence={"install": install, "guardian_admission": admission},
        now=now,
    )
    try:
        activation = _require_ok(ops.activate(plan), "activation")
    except Exception as exc:
        failed = transition_transaction(
            pending,
            UpdateState.ATTENTION_REQUIRED,
            reason="normal candidate activation failed",
            blockers=["normal_activation_failed"],
            evidence={"error": str(exc)},
            now=now,
        )
        return NormalExecutionResult(failed, plan, True)
    verifying = transition_transaction(
        pending,
        UpdateState.ACTIVE_VERIFYING,
        reason="normal candidate activation completed; verification started",
        evidence={"activation": activation},
        now=now,
    )
    try:
        verification = _require_ok(ops.verify(plan), "verification")
    except Exception as exc:
        failed = transition_transaction(
            verifying,
            UpdateState.ATTENTION_REQUIRED,
            reason="normal candidate verification failed",
            blockers=["normal_verification_failed"],
            evidence={"error": str(exc)},
            now=now,
        )
        return NormalExecutionResult(failed, plan, True)
    healthy = transition_transaction(
        verifying,
        UpdateState.HEALTHY,
        reason="normal update generation passed Guardian verification",
        evidence={"verification": verification},
        now=now,
    )
    return NormalExecutionResult(healthy, plan, True)


def _validate_execution_binding(transaction: Mapping[str, Any], plan: NormalExecutionPlan) -> dict[str, Any]:
    current = validate_transaction(transaction)
    if current["state"] != UpdateState.PREPARED.value:
        raise ValueError("normal execution requires PREPARED transaction")
    if current["transaction_id"] != plan.transaction_id or current["package_generation"]["id"] != plan.package_generation_id:
        raise ValueError("normal execution plan does not bind exact transaction")
    if current["source_provenance"]["id"] != plan.source_provenance_id:
        raise ValueError("normal execution provenance generation drifted")
    return current


def execute_normal_update(
    transaction: Mapping[str, Any],
    plan: NormalExecutionPlan,
    ops: NormalUpdateOps,
    *,
    authority: Mapping[str, Any] | None = None,
    now=None,
) -> NormalExecutionResult:
    current = _validate_execution_binding(transaction, plan)
    if plan.execution_environment == "production":
        try:
            if authority is None:
                raise ValueError("normal execution authority missing")
            authorize_normal_plan(
                authority, source_revision=current["source_revision"],
                effects=plan.effects, activation_requirements=plan.activation_requirements,
            )
        except ValueError:
            ready = transition_transaction(
                current,
                UpdateState.MAINTENANCE_READY,
                reason="normal update exact generation is ready for bounded execution",
                evidence={"normal_plan": plan.as_dict()},
                now=now,
            )
            blocked = transition_transaction(
                ready,
                UpdateState.BLOCKED,
                reason="normal production mutation remains uncertified pending hardware proof",
                blockers=["normal_update_execution_uncertified"],
                now=now,
            )
            return NormalExecutionResult(blocked, plan, False)
        if getattr(ops, "production_safe", False) is not True:
            raise ValueError("normal production executor is not certified production-safe")
    elif getattr(ops, "fixture_safe", False) is not True:
        ready = transition_transaction(
            current,
            UpdateState.MAINTENANCE_READY,
            reason="normal update exact generation is ready for bounded execution",
            evidence={"normal_plan": plan.as_dict()},
            now=now,
        )
        blocked = transition_transaction(
            ready,
            UpdateState.BLOCKED,
            reason="normal fixture execution requires fixture-safe provider",
            blockers=["normal_fixture_executor_not_isolated"],
            now=now,
        )
        return NormalExecutionResult(blocked, plan, False)
    return _execute_normal_lifecycle(current, plan, ops, now=now)


def execute_normal_certification(
    transaction: Mapping[str, Any],
    plan: NormalExecutionPlan,
    ops: NormalUpdateOps,
    *,
    confirmation: str,
    now=None,
) -> NormalExecutionResult:
    """One-time host certification path. It never creates future authority itself."""
    current = _validate_execution_binding(transaction, plan)
    if plan.execution_environment != "production":
        raise ValueError("normal certification requires production execution environment")
    if confirmation != certification_confirmation(current["source_revision"]):
        raise ValueError("exact normal certification confirmation token is required")
    if getattr(ops, "production_safe", False) is not True:
        raise ValueError("normal certification requires production-safe executor")
    return _execute_normal_lifecycle(current, plan, ops, now=now)
