#!/usr/bin/env python3
"""Staged battery policy proposals for Maho adaptive policy."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from maho_adaptive_proposal import AdaptationProposal, Effect, ExpiryCondition, create_proposal
from maho_adaptive_situation import SituationSnapshot, UNKNOWN

POLICY_VERSION = "1.0"
AC_RECOVERY_DWELL_SECONDS = 20


@dataclass(frozen=True)
class BatteryAssessment:
    band: str
    confidence: float
    evidence: tuple[str, ...]
    reason: str


def assess_battery(snapshot: SituationSnapshot) -> BatteryAssessment:
    p = snapshot.power
    evidence: list[str] = []
    if p.freshness != "fresh":
        return BatteryAssessment("UNKNOWN", 0.0, (f"power-freshness={p.freshness}",), "battery evidence is not fresh")
    if p.battery_present is not True:
        return BatteryAssessment("NORMAL" if p.battery_present is False else "UNKNOWN", 1.0 if p.battery_present is False else 0.0, (f"battery-present={p.battery_present}",), "no battery is present" if p.battery_present is False else "battery presence is unknown")
    if p.percentage == UNKNOWN or p.ac_online == UNKNOWN:
        return BatteryAssessment("UNKNOWN", 0.0, ("battery percentage or AC state unknown",), "required battery evidence is missing")
    percentage = int(p.percentage)
    evidence.extend((f"battery={percentage}", f"ac={str(p.ac_online).lower()}"))
    if p.charging_state != UNKNOWN:
        evidence.append(f"charge-state={p.charging_state}")
    if p.drain_trend != UNKNOWN:
        evidence.append(f"drain-trend={p.drain_trend}")

    if p.ac_online is True or p.charging_state in {"charging", "full"}:
        if p.ac_stable_seconds == UNKNOWN or float(p.ac_stable_seconds) < AC_RECOVERY_DWELL_SECONDS:
            evidence.append(f"ac-stable-seconds={p.ac_stable_seconds}")
            return BatteryAssessment("UNKNOWN", 0.0, tuple(evidence), "external power has not been stable long enough to release battery pressure")
        evidence.append(f"ac-stable-seconds={p.ac_stable_seconds}")
        return BatteryAssessment("NORMAL", 0.98, tuple(evidence), "stable external power removes battery-survival pressure")
    if percentage <= 7:
        band = "CRITICAL"
    elif percentage <= 18:
        band = "CONSERVING"
    elif percentage <= 35:
        band = "LOW"
    else:
        band = "NORMAL"
    confidence = 0.92
    if p.charging_state == "discharging":
        confidence += 0.04
    if p.drain_trend in {"falling", "rapid-fall"}:
        confidence += 0.03
    return BatteryAssessment(band, min(confidence, 1.0), tuple(evidence), f"battery context is {band.lower()} while off AC")


def _proposal(
    snapshot: SituationSnapshot,
    assessment: BatteryAssessment,
    *,
    source: str,
    disruption: str,
    priority: str,
    effects: Iterable[Effect],
    reason: str,
    dwell: int,
    residency: int,
    cooldown: int,
    created_at: datetime | None,
    notification: str = "none",
    override: str = "respect",
) -> AdaptationProposal:
    return create_proposal(
        source_policy=source,
        policy_version=POLICY_VERSION,
        situation_snapshot_id=snapshot.snapshot_id,
        priority_domain=priority,
        disruption_class=disruption,
        confidence=assessment.confidence,
        reason=reason,
        supporting_evidence=assessment.evidence,
        requested_effects=effects,
        minimum_dwell_seconds=dwell,
        expiry_condition=ExpiryCondition("condition-clears", "battery-survival-context"),
        cooldown_seconds=cooldown,
        minimum_residency_seconds=residency,
        reversibility=True,
        user_override_behavior=override,
        notification_policy=notification,
        verification_requirement="observe",
        failure_behavior="preserve-current",
        created_at=created_at,
    )


def battery_proposals(snapshot: SituationSnapshot, *, created_at: datetime | None = None) -> tuple[AdaptationProposal, ...]:
    """Return declarative proposals only for coherent sustained battery pressure."""
    assessment = assess_battery(snapshot)
    if assessment.band in {"UNKNOWN", "NORMAL"}:
        return ()
    opt_outs = set(snapshot.user_intent.adaptation_opt_outs)
    if "battery" in opt_outs or "power" in opt_outs:
        return ()

    workload = snapshot.workload
    performance_intent = snapshot.user_intent.power_mode == "performance" or snapshot.user_intent.foreground_performance is True
    interactive = workload.probable_gaming is True or workload.interactive is True
    proposals: list[AdaptationProposal] = []

    common = [Effect("maintenance", "suspended")]
    if assessment.band == "LOW":
        common.append(Effect("background_work", "reduced"))
        proposals.append(_proposal(
            snapshot, assessment, source="battery.low", disruption="A", priority="battery-survival",
            effects=common, reason="low battery should defer maintenance and reduce optional background work",
            dwell=45, residency=120, cooldown=90, created_at=created_at,
        ))
    elif assessment.band == "CONSERVING":
        common.extend((Effect("background_work", "reduced"), Effect("power_survival", "conserve")))
        proposals.append(_proposal(
            snapshot, assessment, source="battery.conserving", disruption="B", priority="battery-survival",
            effects=common, reason="sustained low battery requires a conservative reversible background posture",
            dwell=25, residency=150, cooldown=120, created_at=created_at,
        ))
    else:  # CRITICAL
        common.extend((Effect("background_work", "suspended"), Effect("power_survival", "conserve")))
        proposals.append(_proposal(
            snapshot, assessment, source="battery.critical", disruption="B", priority="battery-survival",
            effects=common, reason="critical battery requires stronger survival posture without destructive action",
            dwell=10, residency=120, cooldown=180, created_at=created_at,
            notification="passive",
        ))
        proposals.append(_proposal(
            snapshot, assessment, source="battery.critical-action", disruption="D", priority="battery-survival",
            effects=(Effect("power_action", "suspend-review"),),
            reason="critical battery may warrant a user-reviewed power action; automatic suspend remains disabled",
            dwell=30, residency=0, cooldown=300, created_at=created_at,
            notification="action-required",
        ))

    if interactive or performance_intent:
        proposals.append(_proposal(
            snapshot, assessment, source="battery.foreground-continuity", disruption="A",
            priority="foreground-task-continuity", effects=(Effect("foreground_performance", "preserve"),),
            reason="battery conservation must reduce unrelated work rather than disrupt explicit foreground performance",
            dwell=10, residency=90, cooldown=60, created_at=created_at,
        ))
    return tuple(proposals)
