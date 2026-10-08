#!/usr/bin/env python3
"""Coherent maintenance-opportunity policy layered above M4 native gates."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from maho_adaptive_proposal import AdaptationProposal,Effect,ExpiryCondition,create_proposal
from maho_adaptive_situation import SituationSnapshot,UNKNOWN

POLICY_VERSION="1.0"
LOCK_DWELL_SECONDS=15*60
IDLE_DWELL_SECONDS=20*60
MIN_BATTERY_PERCENT=25
MIN_AC_STABLE_SECONDS=60
MIN_NETWORK_STABLE_SECONDS=60

@dataclass(frozen=True)
class MaintenanceEligibility:
 eligible: bool
 reasons: tuple[str,...]
 must_finish_bounded_critical_section: bool
 recheck_required: bool=True


def assess_maintenance(snapshot:SituationSnapshot)->MaintenanceEligibility:
 s=snapshot.session; p=snapshot.power; t=snapshot.thermal; w=snapshot.workload; n=snapshot.network; m=snapshot.maintenance; g=snapshot.guardian
 # If M4 is already beyond an interruption-safe boundary, policy must not
 # pretend it can cancel. Future executor owns finishing that bounded section.
 if m.in_critical_section is True and m.interruption_safe is False:
  return MaintenanceEligibility(False,("m4_interruption_unsafe_critical_section",),True,True)
 reasons=[]
 for name,fresh in (("session",s.freshness),("power",p.freshness),("thermal",t.freshness),("workload",w.freshness),("network",n.freshness),("maintenance",m.freshness),("guardian",g.freshness)):
  if fresh!="fresh": reasons.append(f"{name}_evidence_{fresh}")
 if s.locked is not True: reasons.append("session_not_locked")
 if s.lock_dwell_seconds==UNKNOWN or float(s.lock_dwell_seconds)<LOCK_DWELL_SECONDS: reasons.append("lock_dwell_too_short_or_unknown")
 if s.idle_seconds==UNKNOWN or float(s.idle_seconds)<IDLE_DWELL_SECONDS: reasons.append("idle_dwell_too_short_or_unknown")
 if s.recent_input_seconds!=UNKNOWN and float(s.recent_input_seconds)<IDLE_DWELL_SECONDS: reasons.append("recent_user_input")
 if s.inhibitors: reasons.append("session_inhibitor_present")
 if p.ac_online is not True or p.ac_stable_seconds==UNKNOWN or float(p.ac_stable_seconds)<MIN_AC_STABLE_SECONDS: reasons.append("stable_ac_required")
 if p.battery_present is True and (p.percentage==UNKNOWN or int(p.percentage)<MIN_BATTERY_PERCENT): reasons.append("battery_not_healthy")
 if t.level not in {"normal","warm"}: reasons.append("thermal_state_not_acceptable")
 if w.confidence==UNKNOWN: reasons.append("workload_confidence_unknown")
 if w.probable_gaming is True or w.interactive is True: reasons.append("interactive_workload")
 if w.probable_compile is True: reasons.append("compile_in_progress")
 if w.probable_rendering is True: reasons.append("render_in_progress")
 if n.connectivity!="online" or n.stability!="stable" or n.default_route is not True or n.stability_seconds==UNKNOWN or float(n.stability_seconds)<MIN_NETWORK_STABLE_SECONDS: reasons.append("network_not_stable")
 if m.prepared is not True or m.transaction_state!="PREPARED": reasons.append("m4_transaction_not_prepared")
 if m.recovery_prerequisites is not True: reasons.append("recovery_prerequisites_unready")
 if m.enough_disk is not True: reasons.append("disk_headroom_unconfirmed")
 if g.recovery_in_progress is not False or g.unresolved_reliability is not False: reasons.append("guardian_reliability_state")
 if g.severity_level==UNKNOWN or int(g.severity_level)>=2: reasons.append("guardian_severity_blocks_maintenance")
 return MaintenanceEligibility(not reasons,tuple(dict.fromkeys(reasons)),False,True)


def maintenance_proposals(snapshot:SituationSnapshot,*,created_at:datetime|None=None)->tuple[AdaptationProposal,...]:
 assessment=assess_maintenance(snapshot)
 if not assessment.eligible: return ()
 evidence=(f"lock-dwell={int(float(snapshot.session.lock_dwell_seconds))}",f"idle={int(float(snapshot.session.idle_seconds))}","ac=true","thermal-acceptable","no-respected-workload","network-stable","m4-prepared","recovery-ready","disk-ready")
 return (create_proposal(source_policy="maintenance.eligible",policy_version=POLICY_VERSION,situation_snapshot_id=snapshot.snapshot_id,
  priority_domain="maintenance",disruption_class="A",confidence=.99,
  reason="coherent sustained idle context permits maintenance policy consideration; M4 native gates remain authoritative",
  supporting_evidence=evidence,requested_effects=[Effect("maintenance","eligible")],minimum_dwell_seconds=30,
  expiry_condition=ExpiryCondition("snapshot-changes","re-evaluate-before-mutation"),cooldown_seconds=30,minimum_residency_seconds=0,
  reversibility=True,user_override_behavior="respect",notification_policy="none",verification_requirement="required",
  failure_behavior="preserve-current",created_at=created_at),)


def recheck_before_mutation(snapshot:SituationSnapshot)->MaintenanceEligibility:
 """Mandatory future executor gate immediately before any mutation boundary."""
 return assess_maintenance(snapshot)
