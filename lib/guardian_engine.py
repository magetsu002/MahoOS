#!/usr/bin/env python3
"""Pure Guardian orchestration: severity + recovery + catastrophic authority."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Any, Mapping
from guardian_catastrophic import assess_catastrophic
from guardian_severity import assess_guardian
from maho_recovery_policy import decide_recovery

_NON_MUTATING_ACTIONS={"diagnose-only","diagnose-service-incident","open-recovery-console","observe-service-recovery"}

@dataclass(frozen=True)
class GuardianDecision:
    severity: dict[str,Any]
    recovery: dict[str,Any]
    catastrophic: dict[str,Any]
    execution_mode: str
    mutating_recovery_allowed: bool
    reason: str
    def as_dict(self)->dict[str,Any]: return asdict(self)

def _action_is_mutating(action:str)->bool:
    return action not in _NON_MUTATING_ACTIONS

def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(mapping: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = mapping.get(key, default)
    return value if isinstance(value, bool) else default


def _authoritative_lower_layer(recovery: Any, recovery_state: Mapping[str, Any]) -> dict[str, Any]:
    """Derive bounded lower-layer trust from the authoritative recovery decision.

    Callers cannot self-assert lower-layer availability through catastrophic
    facts. G1/G2 are certified by exact provider/verified-runtime contracts.
    G3 only counts when its recovery facts explicitly certify coherent state.
    """
    availability = _mapping(recovery_state.get("availability"))
    recovery_facts = _mapping(recovery_state.get("recovery"))

    if (
        recovery.action == "observe-service-recovery"
        and recovery.provider == "systemd-user"
        and recovery.recovery_mode == "delegated"
    ):
        return {"level": 1, "available": True, "certified": True, "trusted": True}

    if (
        recovery.action in {"rollback-maho-runtime", "rollback-previous"}
        and recovery.scope in {"maho-runtime", "runtime"}
        and _bool(availability, "previous_runtime_verified")
    ):
        return {"level": 2, "available": True, "certified": True, "trusted": True}

    if recovery.action == "restore-system-state":
        certified = _bool(recovery_facts, "certified")
        coherent = _bool(recovery_facts, "boot_state_coherent")
        available = _bool(availability, "root_recovery_generation", _bool(availability, "root_snapshot"))
        return {
            "level": 3,
            "available": available,
            "certified": certified,
            "trusted": certified and coherent,
        }

    return {"level": 0, "available": False, "certified": False, "trusted": False}


def evaluate_guardian(guardian_state: Mapping[str, Any], recovery_state: Mapping[str, Any]) -> GuardianDecision:
    recovery = decide_recovery(recovery_state)
    lower_layer = _authoritative_lower_layer(recovery, recovery_state)
    raw_cat = guardian_state.get("catastrophic")
    catastrophic = assess_catastrophic(
        raw_cat if isinstance(raw_cat, Mapping) else {},
        lower_layer_recovery=lower_layer,
    )

    severity_state = dict(guardian_state)
    incident = dict(guardian_state.get("incident") or {}) if isinstance(guardian_state.get("incident"), Mapping) else {}
    if catastrophic.catastrophic:
        incident["catastrophic_authority_confirmed"] = True
        incident["impact"] = "catastrophic"
        incident["evidence_confidence"] = "confirmed"
        if incident.get("scope") not in {"system", "boot", "runtime"}:
            incident["scope"] = "system"
        severity_state["incident"] = incident

    assessment = assess_guardian(severity_state)
    mutating = _action_is_mutating(recovery.action)
    delegated = (
        recovery.action == "observe-service-recovery"
        and recovery.provider == "systemd-user"
        and recovery.recovery_mode == "delegated"
    )
    automatic_mutation = (
        mutating
        and assessment.automatic_recovery_allowed
        and recovery.automatic_allowed
        and not recovery.requires_confirmation
        and assessment.level < 4
        and catastrophic.automatic_host_mutation_allowed
    )

    if assessment.recovery_handoff_required or assessment.level >= 4:
        mode = "handoff"
        automatic_mutation = False
    elif catastrophic.fail_closed and mutating:
        mode = "diagnose"
        automatic_mutation = False
    elif delegated:
        mode = "delegated"
        automatic_mutation = False
    elif recovery.requires_confirmation or (assessment.level == 3 and not assessment.automatic_recovery_allowed):
        mode = "confirm"
        automatic_mutation = False
    elif automatic_mutation:
        mode = "automatic"
    elif not mutating:
        mode = "diagnose"
    else:
        mode = "observe"

    return GuardianDecision(
        severity=assessment.as_dict(),
        recovery=recovery.as_dict(),
        catastrophic=catastrophic.as_dict(),
        execution_mode=mode,
        mutating_recovery_allowed=automatic_mutation,
        reason=(
            f"Guardian L{assessment.level} permits "
            f"{'automatic' if assessment.automatic_recovery_allowed else 'non-automatic'} recovery; "
            f"recovery authority selected {recovery.action} "
            f"({'automatic' if recovery.automatic_allowed and not recovery.requires_confirmation else 'gated'})."
        ),
    )
