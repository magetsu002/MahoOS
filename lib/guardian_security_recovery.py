#!/usr/bin/env python3
"""Security-to-Recovery routing without granting new mutation authority."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping

from guardian_causality import CausalGraph, RelationStrength
from guardian_recovery_registry import certified_runtime_recovery


class SecurityRecoveryOutcome(str, Enum):
    DIAGNOSIS_ONLY = "diagnosis-only"
    AUTHORIZATION_REQUIRED = "authorization-required"
    READY_RUNTIME_RECOVERY = "ready-runtime-recovery"
    READY_OFFLINE_RECOVERY = "ready-offline-recovery"
    EXTERNAL_RECOVERY_REQUIRED = "external-recovery-required"


@dataclass(frozen=True)
class SecurityRecoveryHandoff:
    outcome: SecurityRecoveryOutcome
    incident_id: str
    subject: str
    evidence_preservation_required: bool
    isolation_recommended: bool
    provider: str | None
    action: str | None
    scope: str | None
    target_system_generation_id: str | None
    target_kernel_generation_id: str | None
    requires_explicit_recovery_authorization: bool
    postcondition: str | None
    reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["outcome"] = self.outcome.value
        payload["reasons"] = list(self.reasons)
        return payload


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _signal_kinds(incident: Mapping[str, Any]) -> set[str]:
    rows = incident.get("signals") if isinstance(incident.get("signals"), list) else []
    return {str(row.get("kind")) for row in rows if isinstance(row, Mapping) and row.get("kind")}


def _maho_owned_package(package: str) -> bool:
    return package == "maho" or package.startswith("maho-") or package.startswith("mahoos-")


def _proven_package_integrity(graph: CausalGraph | None, package: str) -> bool:
    if graph is None:
        return False
    source = f"subject:package:{package}"
    return any(
        edge.source == source
        and edge.strength is RelationStrength.PROVEN
        and edge.relation == "package-owns-file"
        for edge in graph.edges
    )


def _offline_value(plan: Any, name: str, default: Any = None) -> Any:
    if plan is None:
        return default
    if isinstance(plan, Mapping):
        return plan.get(name, default)
    return getattr(plan, name, default)


def plan_security_recovery(
    incident: Mapping[str, Any],
    *,
    causal_graph: CausalGraph | None = None,
    runtime_transaction_authorized: bool = False,
    previous_runtime_available: bool = False,
    offline_plan: Any = None,
) -> SecurityRecoveryHandoff:
    iid = str(incident.get("incident_id") or "")
    subject = _mapping(incident.get("subject"))
    subject_type = str(subject.get("type") or "unknown")
    subject_id = str(subject.get("id") or "unknown")
    subject_name = f"{subject_type}:{subject_id}"
    kinds = _signal_kinds(incident)
    contamination_signal = bool(kinds & {"integrity-drift", "package-provenance-untrusted", "executable-provenance-untrusted"})

    def handoff(outcome: SecurityRecoveryOutcome, *reasons: str, **kwargs: Any) -> SecurityRecoveryHandoff:
        return SecurityRecoveryHandoff(
            outcome=outcome,
            incident_id=iid,
            subject=subject_name,
            evidence_preservation_required=True,
            isolation_recommended=contamination_signal,
            provider=kwargs.get("provider"),
            action=kwargs.get("action"),
            scope=kwargs.get("scope"),
            target_system_generation_id=kwargs.get("target_system_generation_id"),
            target_kernel_generation_id=kwargs.get("target_kernel_generation_id"),
            requires_explicit_recovery_authorization=kwargs.get("requires_authorization", False),
            postcondition=kwargs.get("postcondition"),
            reasons=tuple(dict.fromkeys(reasons)),
        )

    if not iid or incident.get("status") == "resolved":
        return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "no active security incident is available")
    if not contamination_signal:
        return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "incident does not establish trusted-component contamination")

    if subject_type == "package":
        if not _maho_owned_package(subject_id):
            return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "third-party or user-owned package has no Guardian mutation authority")
        if not _proven_package_integrity(causal_graph, subject_id):
            return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "component contamination is not causally proven to an exact trusted package file")
        contract = certified_runtime_recovery(subject_id)
        if contract is None:
            return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "Maho component has no certified recovery provider for this exact scope")
        if contract.previous_runtime_required and not previous_runtime_available:
            return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "certified runtime rollback requires a verified previous runtime")
        if contract.automatic_only_in_transaction and not runtime_transaction_authorized:
            return handoff(
                SecurityRecoveryOutcome.AUTHORIZATION_REQUIRED,
                "certified runtime recovery exists but the security incident cannot self-authorize the transaction",
                provider=contract.provider,
                action=contract.action,
                scope=contract.scope,
                requires_authorization=True,
                postcondition=contract.postcondition,
            )
        return handoff(
            SecurityRecoveryOutcome.READY_RUNTIME_RECOVERY,
            "exact contaminated Maho runtime maps to the existing certified transactional rollback",
            provider=contract.provider,
            action=contract.action,
            scope=contract.scope,
            requires_authorization=True,
            postcondition=contract.postcondition,
        )

    if subject_type in {"host", "system", "kernel"}:
        outcome = str(_offline_value(offline_plan, "outcome", ""))
        if outcome != "READY":
            return handoff(
                SecurityRecoveryOutcome.EXTERNAL_RECOVERY_REQUIRED,
                "system-level contamination has no independently certified clean recovery source",
                requires_authorization=True,
            )
        return handoff(
            SecurityRecoveryOutcome.READY_OFFLINE_RECOVERY,
            "independently verified offline recovery plan supplies the smallest certified clean generation pair",
            provider=str(_offline_value(offline_plan, "provider_id", "guardian-offline")),
            action="stage-certified-generation-restore",
            scope="system-generation+kernel-generation",
            target_system_generation_id=str(_offline_value(offline_plan, "target_system_generation_id") or "") or None,
            target_kernel_generation_id=str(_offline_value(offline_plan, "target_kernel_generation_id") or "") or None,
            requires_authorization=True,
            postcondition="verify-staged-artifacts-and-post-recovery-world-state-before-trust-restoration",
        )

    return handoff(SecurityRecoveryOutcome.DIAGNOSIS_ONLY, "subject type has no certified Guardian recovery mapping")
