#!/usr/bin/env python3
"""Network-dependent background policy. Never mutates foreground connectivity."""
from __future__ import annotations
from datetime import datetime
from maho_adaptive_proposal import AdaptationProposal,Effect,ExpiryCondition,create_proposal
from maho_adaptive_situation import SituationSnapshot
POLICY_VERSION="1.0"

def network_proposals(snapshot:SituationSnapshot,*,created_at:datetime|None=None)->tuple[AdaptationProposal,...]:
 n=snapshot.network
 if n.freshness!="fresh": return ()
 if "network" in set(snapshot.user_intent.adaptation_opt_outs): return ()
 evidence=(f"connectivity={n.connectivity}",f"stability={n.stability}",f"default-route={n.default_route}",f"reachable={n.reachable}")
 common=dict(policy_version=POLICY_VERSION,situation_snapshot_id=snapshot.snapshot_id,priority_domain="background-efficiency",
  disruption_class="A",confidence=.95, supporting_evidence=evidence,expiry_condition=ExpiryCondition("condition-clears","network-stable-dwell"),
  minimum_residency_seconds=45,cooldown_seconds=60,reversibility=True,user_override_behavior="respect",notification_policy="none",
  verification_requirement="observe",failure_behavior="preserve-current",created_at=created_at)
 if n.connectivity=="offline" or n.default_route is False or n.reachable is False:
  return (create_proposal(source_policy="network.absent",reason="network-dependent background operations should pause while connectivity is unavailable",
   requested_effects=[Effect("network_background","suspended"),Effect("update_downloads","deferred")],minimum_dwell_seconds=10,**common),)
 if n.stability=="unstable" or n.connectivity=="limited":
  return (create_proposal(source_policy="network.unstable",reason="unstable connectivity should defer update transfer and reduce retry pressure without touching foreground networking",
   requested_effects=[Effect("network_background","reduced"),Effect("update_downloads","deferred"),Effect("foreground_network","preserve")],minimum_dwell_seconds=20,**common),)
 return ()
