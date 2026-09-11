#!/usr/bin/env python3
"""Dwell- and hysteresis-aware thermal policy proposals."""
from __future__ import annotations

from datetime import datetime
from maho_adaptive_proposal import AdaptationProposal, Effect, ExpiryCondition, create_proposal
from maho_adaptive_situation import SituationSnapshot, UNKNOWN

POLICY_VERSION="1.0"
HOT_DWELL_SECONDS=60
CRITICAL_DWELL_SECONDS=20


def thermal_proposals(snapshot: SituationSnapshot, *, created_at: datetime | None=None) -> tuple[AdaptationProposal,...]:
    t=snapshot.thermal
    if t.freshness != "fresh" or t.level == UNKNOWN or t.sustained_seconds == UNKNOWN:
        return ()
    if "thermal" in set(snapshot.user_intent.adaptation_opt_outs):
        # Thermal optimization respects opt-out; genuine hardware safety would
        # be a separate hardware/data-safety authority, not invented here.
        return ()
    dwell=float(t.sustained_seconds)
    evidence=[f"thermal={t.level}",f"sustained={int(dwell)}"]
    if t.maximum_millidegree_c != UNKNOWN:
        evidence.append(f"max-mc={t.maximum_millidegree_c}")
    if t.trend != UNKNOWN:
        evidence.append(f"trend={t.trend}")
    common=dict(
        policy_version=POLICY_VERSION,
        situation_snapshot_id=snapshot.snapshot_id,
        priority_domain="thermal-protection",
        confidence=.97 if t.trend in {"rising","stable"} else .9,
        supporting_evidence=evidence,
        expiry_condition=ExpiryCondition("condition-clears","thermal-recovery-dwell"),
        reversibility=True,user_override_behavior="respect",
        verification_requirement="observe",failure_behavior="preserve-current",
        created_at=created_at,
    )
    if t.level in {"normal","warm"}:
        return ()
    if t.level == "hot":
        if dwell < HOT_DWELL_SECONDS:
            return ()
        return (create_proposal(
            source_policy="thermal.hot-sustained",disruption_class="A",
            reason="sustained hot thermal state should suspend maintenance and reduce optional background activity",
            requested_effects=[Effect("maintenance","suspended"),Effect("background_work","reduced"),Effect("thermal_protection","elevated")],
            minimum_dwell_seconds=HOT_DWELL_SECONDS,minimum_residency_seconds=120,cooldown_seconds=90,
            notification_policy="none",**common),)
    if dwell < CRITICAL_DWELL_SECONDS:
        return ()
    protective=create_proposal(
        source_policy="thermal.critical-sustained",disruption_class="B",
        reason="sustained critical thermal state requires stronger reversible protection without destructive behavior",
        requested_effects=[Effect("maintenance","suspended"),Effect("background_work","suspended"),Effect("thermal_protection","critical-review")],
        minimum_dwell_seconds=CRITICAL_DWELL_SECONDS,minimum_residency_seconds=180,cooldown_seconds=180,
        notification_policy="passive",**common)
    # Class C is modeled but review-only. It cannot execute in A1-A14.
    review=create_proposal(
        source_policy="thermal.critical-visible",disruption_class="C",
        reason="a visible performance-mode reduction may help critical heat but requires human review in this milestone",
        requested_effects=[Effect("performance_mode","conservative")],
        minimum_dwell_seconds=60,minimum_residency_seconds=120,cooldown_seconds=300,
        notification_policy="action-required",**common)
    return protective,review
