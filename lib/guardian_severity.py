#!/usr/bin/env python3
"""Pure Guardian severity policy for MahoOS.

This module classifies normalized incident state into Guardian presentation
levels. It never performs recovery and never chooses a concrete recovery
action. Recovery selection remains the responsibility of
``maho_recovery_policy`` and execution adapters behind their own authority
boundaries.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping


LEVEL_LABELS = {
    0: "normal",
    1: "minor",
    2: "component",
    3: "session",
    4: "catastrophic",
}

_CONFIDENCE = {"low": 0, "medium": 1, "high": 2, "confirmed": 3}
_RECOVERY_CONFIDENCE = {"none": 0, "low": 1, "medium": 2, "high": 3, "certified": 4}
_IMPACT = {"none": 0, "minor": 1, "degraded": 2, "unavailable": 3, "catastrophic": 4}


@dataclass(frozen=True)
class GuardianAssessment:
    level: int
    label: str
    suppressed: bool
    automatic_recovery_allowed: bool
    recovery_handoff_required: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(mapping: Mapping[str, Any], key: str, default: bool = False) -> bool:
    value = mapping.get(key, default)
    return value if isinstance(value, bool) else default


def _int(mapping: Mapping[str, Any], key: str, default: int = 0) -> int:
    value = mapping.get(key, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _enum(mapping: Mapping[str, Any], key: str, allowed: set[str], default: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) and value in allowed else default


def assess_guardian(state: Mapping[str, Any]) -> GuardianAssessment:
    """Classify normalized state into Guardian L0-L4 without choosing an action.

    Expected normalized groups:

    ``incident``
        scope, ownership, impact, evidence_confidence, persistent,
        occurrence_count, correlated_failures, resolved

    ``recovery``
        confidence, certified_path, previous_failures, verified

    ``context``
        maintenance, expected_transition

    Unknown or malformed values fail closed. Severity may still be surfaced for
    user awareness, but autonomous recovery is permitted only for Maho-owned,
    high-confidence, explicitly certified recovery paths.
    """

    incident = _mapping(state.get("incident"))
    recovery = _mapping(state.get("recovery"))
    context = _mapping(state.get("context"))

    if _bool(context, "maintenance") or _bool(context, "expected_transition"):
        return GuardianAssessment(
            level=0,
            label=LEVEL_LABELS[0],
            suppressed=True,
            automatic_recovery_allowed=False,
            recovery_handoff_required=False,
            reason="Expected maintenance/session transition is suppressed from Guardian escalation.",
        )

    scope = _enum(
        incident,
        "scope",
        {"component", "session", "runtime", "system", "boot", "unknown"},
        "unknown",
    )
    ownership = _enum(incident, "ownership", {"maho", "user", "unknown"}, "unknown")
    impact = _enum(incident, "impact", set(_IMPACT), "none")
    evidence = _enum(incident, "evidence_confidence", set(_CONFIDENCE), "low")
    recovery_confidence = _enum(
        recovery,
        "confidence",
        set(_RECOVERY_CONFIDENCE),
        "none",
    )

    occurrences = max(0, _int(incident, "occurrence_count", 0))
    correlated = max(0, _int(incident, "correlated_failures", 0))
    previous_failures = max(0, _int(recovery, "previous_failures", 0))
    persistent = _bool(incident, "persistent") or occurrences >= 3
    resolved = _bool(incident, "resolved")
    certified_path = _bool(recovery, "certified_path")
    recovery_verified = _bool(recovery, "verified")

    impact_rank = _IMPACT[impact]
    evidence_rank = _CONFIDENCE[evidence]
    recovery_rank = _RECOVERY_CONFIDENCE[recovery_confidence]

    # Verification closes an incident only when the normalized incident itself
    # is also resolved. A stale "verified" recovery flag must not hide current
    # catastrophic evidence.
    if recovery_verified and resolved:
        return GuardianAssessment(
            level=0,
            label=LEVEL_LABELS[0],
            suppressed=False,
            automatic_recovery_allowed=False,
            recovery_handoff_required=False,
            reason="Recovery and incident resolution were both verified; Guardian de-escalates.",
        )

    # Completely empty/malformed input is not itself an anomaly.
    if (
        impact_rank == _IMPACT["none"]
        and occurrences == 0
        and correlated == 0
        and not persistent
        and not resolved
    ):
        return GuardianAssessment(
            level=0,
            label=LEVEL_LABELS[0],
            suppressed=False,
            automatic_recovery_allowed=False,
            recovery_handoff_required=False,
            reason="No actionable degradation is present.",
        )

    # L4 is diagnosis/handoff only. Weak evidence can never throw the wheel
    # into catastrophic mode, and L4 never grants automatic recovery.
    if (
        scope in {"system", "boot"}
        and impact_rank >= _IMPACT["catastrophic"]
        and evidence_rank >= _CONFIDENCE["high"]
    ):
        return GuardianAssessment(
            level=4,
            label=LEVEL_LABELS[4],
            suppressed=False,
            automatic_recovery_allowed=False,
            recovery_handoff_required=True,
            reason="High-confidence catastrophic system/boot impact requires explicit recovery handoff.",
        )

    # L3 is reserved for correlated Maho session/runtime failure after a
    # narrower recovery already failed. The broader path must itself be
    # certified before Guardian may present this as L3.
    l3_candidate = (
        ownership == "maho"
        and scope in {"session", "runtime", "system"}
        and correlated >= 2
        and previous_failures >= 1
        and impact_rank >= _IMPACT["degraded"]
        and evidence_rank >= _CONFIDENCE["high"]
    )
    if l3_candidate and certified_path:
        automatic = recovery_rank >= _RECOVERY_CONFIDENCE["certified"]
        return GuardianAssessment(
            level=3,
            label=LEVEL_LABELS[3],
            suppressed=False,
            automatic_recovery_allowed=automatic,
            recovery_handoff_required=not automatic,
            reason=(
                "Correlated Maho session/runtime failure persisted after a narrower recovery; "
                "the broader recovery path is explicitly certified."
            ),
        )

    # Repeated high-confidence degradation becomes L2. Unknown or user
    # ownership may still be surfaced, but can never authorize Maho mutation.
    l2_candidate = (
        impact_rank >= _IMPACT["degraded"]
        and persistent
        and evidence_rank >= _CONFIDENCE["high"]
    )
    if l2_candidate:
        automatic = (
            ownership == "maho"
            and scope == "component"
            and certified_path
            and recovery_rank >= _RECOVERY_CONFIDENCE["certified"]
        )
        return GuardianAssessment(
            level=2,
            label=LEVEL_LABELS[2],
            suppressed=False,
            automatic_recovery_allowed=automatic,
            recovery_handoff_required=False,
            reason="Persistent high-confidence degradation warrants bounded L2 attention.",
        )

    # L1 is a transient or weakly evidenced anomaly. A tiny, certified,
    # Maho-owned correction may run automatically; L1 never authorizes a
    # disruptive or uncertified recovery.
    if impact_rank > _IMPACT["none"] or occurrences > 0 or correlated > 0 or persistent:
        automatic = (
            ownership == "maho"
            and scope == "component"
            and impact_rank <= _IMPACT["minor"]
            and evidence_rank >= _CONFIDENCE["high"]
            and certified_path
            and recovery_rank >= _RECOVERY_CONFIDENCE["certified"]
        )
        return GuardianAssessment(
            level=1,
            label=LEVEL_LABELS[1],
            suppressed=False,
            automatic_recovery_allowed=automatic,
            recovery_handoff_required=False,
            reason="Transient, weakly evidenced, or narrowly scoped anomaly remains at L1.",
        )

    return GuardianAssessment(
        level=0,
        label=LEVEL_LABELS[0],
        suppressed=False,
        automatic_recovery_allowed=False,
        recovery_handoff_required=False,
        reason="No actionable degradation is present.",
    )


def assessment_json(state: Mapping[str, Any]) -> str:
    return json.dumps(
        assess_guardian(state).as_dict(),
        sort_keys=True,
        separators=(",", ":"),
    )
