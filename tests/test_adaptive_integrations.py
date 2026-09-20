#!/usr/bin/env python3
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from maho_adaptive_integrations import guardian_proposals,project_m4_context
from maho_adaptive_situation import build_situation
from maho_update_maintenance import MaintenanceContext,evaluate_maintenance
from maho_update_state import UpdateState,create_transaction,transition_transaction
NOW=datetime(2026,9,12,5,0,tzinfo=timezone.utc);F="2026-09-12T04:59:30Z"
def prepared():
 t=create_transaction(transaction_id="upd-20260912T050000Z-123456abcdef",source_revision="e"*40,packages=[{"name":"demo","installed_version":"1","candidate_version":"2","repository":"core","roles":[]}],activation_requirements=[],recovery_generation_id=None,now=NOW)
 t=transition_transaction(t,UpdateState.STAGED,now=NOW);return transition_transaction(t,UpdateState.PREPARED,now=NOW)
def ctx(**kw):
 d=dict(intent="none",active_user=False,fullscreen_or_gaming=False,idle_seconds=3600,locked=True,power_status_known=True,on_ac=True,battery_percent=100,system_safe=True,concurrent_package_or_build_operation=False,unattended_allowed=True,serious_security_issue=False,update_debt_days=2);d.update(kw);return MaintenanceContext(**d)
def gs(level=0,incident=False,recovery=False,unresolved=False):
 return build_situation({"guardian":{"observed_at":F,"data":{"severity_level":level,"active_incident":incident,"recovery_in_progress":recovery,"unresolved_reliability":unresolved}}},captured_at=NOW)
def main():
 assert guardian_proposals(gs(),created_at=NOW)==()
 assert guardian_proposals(gs(1,True,False,False),created_at=NOW)==()
 rec=guardian_proposals(gs(3,True,True,True),created_at=NOW);fx={(e.key,e.value) for p in rec for e in p.requested_effects};assert ("maintenance","suspended") in fx and ("background_work","reduced") in fx
 # Adaptive suspension vetoes an otherwise native-eligible M4 opportunity.
 suspended=evaluate_maintenance(prepared(),project_m4_context(ctx(),{"maintenance":"suspended"}),now=NOW)
 assert not suspended.may_begin and "adaptive_maintenance_suspended" in suspended.reasons
 explicit_suspended=evaluate_maintenance(prepared(),project_m4_context(ctx(intent="explicit-update"),{"maintenance":"suspended"}),now=NOW)
 assert not explicit_suspended.may_begin and "adaptive_maintenance_suspended" in explicit_suspended.reasons
 # Adaptive eligibility is permission only; native active-user gate still wins.
 native_block=evaluate_maintenance(prepared(),project_m4_context(ctx(active_user=True),{"maintenance":"eligible"}),now=NOW)
 assert not native_block.may_begin and "active_user" in native_block.reasons
 # When both policy permission and every native M4 gate agree, M4 owns transition.
 allowed=evaluate_maintenance(prepared(),project_m4_context(ctx(),{"maintenance":"eligible"}),now=NOW)
 assert allowed.may_begin and allowed.transaction["state"]=="MAINTENANCE_READY"
 # Legacy M4A callers remain exact-compatible when no adaptive projection exists.
 legacy=evaluate_maintenance(prepared(),ctx(),now=NOW);assert legacy.may_begin
 print("ALL ADAPTIVE GUARDIAN/M4 INTEGRATION TESTS PASS")
if __name__=="__main__":main()
