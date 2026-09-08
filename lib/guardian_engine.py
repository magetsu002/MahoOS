#!/usr/bin/env python3
"""Pure Guardian orchestration: severity authority + recovery authority.

This module does not execute recovery. It combines two independently pure
decisions and returns the only execution posture the runtime is allowed to
consider.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from guardian_severity import assess_guardian
from maho_recovery_policy import decide_recovery

_NON_MUTATING_ACTIONS = {
    "diagnose-only",
    "diagnose-service-incident",
    "open-recovery-console",
}

@dataclass(frozen=True)
class GuardianDecision:
    severity: dict[str, Any]
    recovery: dict[str, Any]
    execution_mode: str
    mutating_recovery_allowed: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

def _action_is_mutating(action: str) -> bool:
    # Unknown actions fail closed as mutating.
    return action not in _NON_MUTATING_ACTIONS

def evaluate_guardian(
    guardian_state: Mapping[str, Any],
    recovery_state: Mapping[str, Any],
) -> GuardianDecision:
    assessment = assess_guardian(guardian_state)
    recovery = decide_recovery(recovery_state)
    mutating = _action_is_mutating(recovery.action)

    automatic_mutation = (
        mutating
        and assessment.automatic_recovery_allowed
        and recovery.automatic_allowed
        and not recovery.requires_confirmation
        and assessment.level < 4
    )

    if assessment.recovery_handoff_required or assessment.level >= 4:
        mode = "handoff"
        automatic_mutation = False
    elif recovery.requires_confirmation or (
        assessment.level == 3 and not assessment.automatic_recovery_allowed
    ):
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
        execution_mode=mode,
        mutating_recovery_allowed=automatic_mutation,
        reason=(
            f"Guardian L{assessment.level} permits "
            f"{'automatic' if assessment.automatic_recovery_allowed else 'non-automatic'} recovery; "
            f"recovery authority selected {recovery.action} "
            f"({'automatic' if recovery.automatic_allowed and not recovery.requires_confirmation else 'gated'})."
        ),
    )
