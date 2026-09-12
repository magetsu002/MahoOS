#!/usr/bin/env python3
"""Foreground-continuity workload policies."""
from __future__ import annotations
from datetime import datetime
from maho_adaptive_proposal import AdaptationProposal,Effect,ExpiryCondition,create_proposal
from maho_adaptive_situation import SituationSnapshot,UNKNOWN
POLICY_VERSION="1.0"; MIN_CONFIDENCE=.75

def _make(snapshot,source,reason,effects,*,created_at,dwell=10,residency=90,cooldown=45):
 return create_proposal(source_policy=source,policy_version=POLICY_VERSION,situation_snapshot_id=snapshot.snapshot_id,
  priority_domain="foreground-task-continuity",disruption_class="A",confidence=float(snapshot.workload.confidence),
  reason=reason,supporting_evidence=snapshot.workload.evidence or (source,),requested_effects=effects,
  minimum_dwell_seconds=dwell,expiry_condition=ExpiryCondition("condition-clears",source),cooldown_seconds=cooldown,
  minimum_residency_seconds=residency,reversibility=True,user_override_behavior="respect",notification_policy="none",
  verification_requirement="observe",failure_behavior="preserve-current",created_at=created_at)

def workload_proposals(snapshot:SituationSnapshot,*,created_at:datetime|None=None)->tuple[AdaptationProposal,...]:
 w=snapshot.workload
 if w.freshness!="fresh" or w.confidence==UNKNOWN or float(w.confidence)<MIN_CONFIDENCE: return ()
 if "workload" in set(snapshot.user_intent.adaptation_opt_outs): return ()
 proposals=[]
 if w.probable_gaming is True:
  proposals.append(_make(snapshot,"gaming.foreground","high-confidence game context should be protected from Maho-generated interference",
   [Effect("maintenance","suspended"),Effect("notifications","quiet"),Effect("background_work","reduced"),Effect("foreground_performance","preserve")],created_at=created_at))
 elif w.interactive is True:
  proposals.append(_make(snapshot,"workload.interactive","high-confidence interactive foreground work should be protected from maintenance and background interference",
   [Effect("maintenance","suspended"),Effect("background_work","reduced"),Effect("foreground_performance","preserve")],created_at=created_at))
 if w.probable_compile is True:
  proposals.append(_make(snapshot,"compile.sustained","a sustained build is meaningful work even while the session is locked",
   [Effect("maintenance","suspended")],created_at=created_at,dwell=15,residency=120))
 if w.probable_rendering is True:
  proposals.append(_make(snapshot,"render.sustained","a sustained rendering or encoding job must not be mistaken for idle maintenance opportunity",
   [Effect("maintenance","suspended")],created_at=created_at,dwell=20,residency=120))
 if w.probable_media is True and w.fullscreen is True:
  proposals.append(_make(snapshot,"media.fullscreen","fullscreen media warrants quiet noncritical notifications without being classified as gaming",
   [Effect("notifications","quiet")],created_at=created_at,dwell=5,residency=30,cooldown=20))
 return tuple(proposals)
