#!/usr/bin/env python3
"""Bounded Guardian and M4 integration for adaptive policy."""
from __future__ import annotations
from dataclasses import replace
from datetime import datetime
from typing import Mapping

from maho_adaptive_proposal import AdaptationProposal,Effect,ExpiryCondition,create_proposal
from maho_adaptive_resolver import ResolvedPosture
from maho_adaptive_situation import SituationSnapshot,UNKNOWN
from maho_update_maintenance import MaintenanceContext

POLICY_VERSION="1.0"


def guardian_proposals(snapshot:SituationSnapshot,*,created_at:datetime|None=None)->tuple[AdaptationProposal,...]:
 g=snapshot.guardian
 if g.freshness!="fresh": return ()
 severe=g.severity_level!=UNKNOWN and int(g.severity_level)>=2
 # Guardian owns incident truth. A current L1 diagnostic remains visible but
 # cannot become a permanent maintenance veto; only L2+, active recovery, or
 # unresolved canonical reliability state has blocking authority.
 if not (g.recovery_in_progress is True or g.unresolved_reliability is True or severe): return ()
 evidence=[f"incident={g.active_incident}",f"recovery={g.recovery_in_progress}",f"unresolved={g.unresolved_reliability}",f"severity={g.severity_level}"]
 effects=[Effect("maintenance","suspended")]
 if g.recovery_in_progress is True or (g.severity_level!=UNKNOWN and int(g.severity_level)>=3):
  effects.append(Effect("background_work","reduced"))
 return (create_proposal(source_policy="guardian.reliability-state",policy_version=POLICY_VERSION,situation_snapshot_id=snapshot.snapshot_id,
  priority_domain="reliability-recovery",disruption_class="A",confidence=.99,reason="Guardian recovery or unresolved reliability state must prevent unrelated maintenance and optimization interference",
  supporting_evidence=evidence,requested_effects=effects,minimum_dwell_seconds=0,expiry_condition=ExpiryCondition("condition-clears","guardian-reliability-state"),
  cooldown_seconds=30,minimum_residency_seconds=0,reversibility=True,user_override_behavior="safety-may-override",notification_policy="none",
  verification_requirement="required",failure_behavior="preserve-current",created_at=created_at),)


def m4_maintenance_value(posture:ResolvedPosture|Mapping[str,str])->str:
 values=dict(posture.effective_posture) if isinstance(posture,ResolvedPosture) else dict(posture)
 value=values.get("maintenance","unknown")
 return value if value in {"eligible","suspended","unchanged"} else "unknown"


def project_m4_context(context:MaintenanceContext,posture:ResolvedPosture|Mapping[str,str])->MaintenanceContext:
 """Project adaptive permission/veto into M4 without changing native authority."""
 return replace(context,adaptive_maintenance=m4_maintenance_value(posture))
