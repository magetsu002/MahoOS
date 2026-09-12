#!/usr/bin/env python3
"""Notification-context policy projected onto the existing Maho Notify authority."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from datetime import datetime
from maho_adaptive_proposal import AdaptationProposal,Effect,ExpiryCondition,create_proposal
from maho_adaptive_situation import SituationSnapshot
POLICY_VERSION="1.0"

@dataclass(frozen=True)
class AdaptiveNotification:
 kind:str
 severity:str="info"
 user_action_required:bool=False
 hardware_or_data_danger:bool=False
 successful_recovery:bool=False

@dataclass(frozen=True)
class NotificationRoute:
 authority:str
 delivery:str
 durable_record_required:bool
 suppress_popup:bool
 reason:str
 def as_dict(self):return asdict(self)

def notification_context_proposals(snapshot:SituationSnapshot,*,created_at:datetime|None=None)->tuple[AdaptationProposal,...]:
 proposals=[]
 if snapshot.user_intent.freshness=="fresh" and snapshot.user_intent.dnd is True:
  proposals.append(create_proposal(source_policy="notification.dnd",policy_version=POLICY_VERSION,situation_snapshot_id=snapshot.snapshot_id,
   priority_domain="explicit-user-intent",disruption_class="A",confidence=1.0,reason="explicit DND suppresses noncritical adaptive notification delivery",
   supporting_evidence=["dnd=true"],requested_effects=[Effect("notifications","quiet")],minimum_dwell_seconds=0,
   expiry_condition=ExpiryCondition("condition-clears","dnd"),cooldown_seconds=0,minimum_residency_seconds=0,reversibility=True,
   user_override_behavior="respect",notification_policy="none",verification_requirement="observe",failure_behavior="preserve-current",created_at=created_at))
 elif snapshot.workload.freshness=="fresh" and (snapshot.workload.probable_gaming is True or (snapshot.workload.probable_media is True and snapshot.workload.fullscreen is True)):
  proposals.append(create_proposal(source_policy="notification.foreground-context",policy_version=POLICY_VERSION,situation_snapshot_id=snapshot.snapshot_id,
   priority_domain="foreground-task-continuity",disruption_class="A",confidence=float(snapshot.workload.confidence) if isinstance(snapshot.workload.confidence,float) else .8,
   reason="gaming or fullscreen media should keep noncritical adaptive notifications quiet",
   supporting_evidence=list(snapshot.workload.evidence) or ["fullscreen-context"],requested_effects=[Effect("notifications","quiet")],minimum_dwell_seconds=5,
   expiry_condition=ExpiryCondition("condition-clears","foreground-context"),cooldown_seconds=15,minimum_residency_seconds=15,reversibility=True,
   user_override_behavior="respect",notification_policy="none",verification_requirement="observe",failure_behavior="preserve-current",created_at=created_at))
 return tuple(proposals)

def route_notification(snapshot:SituationSnapshot,event:AdaptiveNotification)->NotificationRoute:
 """Choose presentation policy only; Maho Notify remains the delivery authority."""
 quiet=(snapshot.user_intent.dnd is True or snapshot.workload.probable_gaming is True or (snapshot.workload.probable_media is True and snapshot.workload.fullscreen is True))
 if event.hardware_or_data_danger or event.severity=="critical":
  return NotificationRoute("maho-notify","prominent",True,False,"hardware/data danger remains visible and durably recorded")
 if event.user_action_required:
  return NotificationRoute("maho-notify","one-concise-notification",True,False,"user action is required; deliver one concise handoff")
 if event.successful_recovery:
  return NotificationRoute("maho-notify","passive-history",True,True,"successful self-recovery is recorded without popup culture")
 if event.kind in {"adaptation-success","temporary-power-posture","temporary-thermal-posture"}:
  return NotificationRoute("maho-notify","history-only",True,True,"routine successful adaptation stays silent")
 if quiet:
  return NotificationRoute("maho-notify","deferred-history",True,True,"noncritical notification is deferred by foreground/DND context and not lost")
 return NotificationRoute("maho-notify","passive",True,True,"noncritical adaptive event remains passive")
