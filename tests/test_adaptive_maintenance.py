#!/usr/bin/env python3
from datetime import datetime,timezone
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'lib'))
from maho_adaptive_maintenance import assess_maintenance,maintenance_proposals,recheck_before_mutation
from maho_adaptive_situation import build_situation
NOW=datetime(2026,9,12,tzinfo=timezone.utc); F="2026-09-11T23:59:30Z"
def env(d):return {"observed_at":F,"data":d}
def snap(**changes):
 d={
 "session":{"locked":True,"lock_dwell_seconds":1200,"idle_seconds":1500,"recent_input_seconds":1500,"inhibitors":[]},
 "power":{"battery_present":True,"percentage":80,"ac_online":True,"charging_state":"charging","ac_stable_seconds":600},
 "thermal":{"max_millidegree_c":70000,"sustained_seconds":500,"trend":"stable"},
 "workload":{"probable_gaming":False,"probable_compile":False,"probable_rendering":False,"probable_media":False,"interactive":False,"confidence":.9},
 "network":{"connectivity":"online","stability":"stable","stability_seconds":600,"default_route":True,"reachable":True},
 "maintenance":{"transaction_state":"PREPARED","pending":True,"staged":True,"prepared":True,"recovery_prerequisites":True,"in_critical_section":False,"interruption_safe":True,"enough_disk":True},
 "guardian":{"active_incident":False,"severity_level":0,"recovery_in_progress":False,"unresolved_reliability":False},
 "user_intent":{"adaptation_opt_outs":[]}}
 for domain,patch in changes.items(): d[domain].update(patch)
 return build_situation({k:env(v) for k,v in d.items()},captured_at=NOW)
def blocked(reason,**kwargs):
 a=assess_maintenance(snap(**kwargs));assert not a.eligible and reason in a.reasons,(reason,a.reasons)
def main():
 ok=snap(); assert assess_maintenance(ok).eligible; p=maintenance_proposals(ok,created_at=NOW); assert len(p)==1; assert p[0].requested_effects[0].value=="eligible"
 blocked("lock_dwell_too_short_or_unknown",session={"lock_dwell_seconds":1})
 blocked("lock_dwell_too_short_or_unknown",session={"lock_dwell_seconds":5})
 blocked("session_not_locked",session={"locked":False,"lock_dwell_seconds":0})
 blocked("compile_in_progress",workload={"probable_compile":True})
 blocked("render_in_progress",workload={"probable_rendering":True})
 blocked("thermal_state_not_acceptable",thermal={"max_millidegree_c":90000,"sustained_seconds":500})
 blocked("stable_ac_required",power={"ac_online":False,"charging_state":"discharging","ac_stable_seconds":0})
 blocked("stable_ac_required",power={"ac_online":True,"charging_state":"charging","ac_stable_seconds":5})
 blocked("network_not_stable",network={"stability":"unstable","stability_seconds":0})
 blocked("network_not_stable",network={"stability":"stable","stability_seconds":5})
 blocked("session_inhibitor_present",session={"inhibitors":["sleep:blocked"]})
 blocked("disk_headroom_unconfirmed",maintenance={"enough_disk":False})
 blocked("recovery_prerequisites_unready",maintenance={"recovery_prerequisites":False})
 # A current low-confidence L1 remains Guardian-visible without becoming an
 # indefinite maintenance veto. Canonical unresolved reliability still blocks.
 assert assess_maintenance(snap(guardian={"active_incident":True,"severity_level":1})).eligible
 blocked("guardian_severity_blocks_maintenance",guardian={"active_incident":True,"severity_level":2})
 blocked("guardian_reliability_state",guardian={"active_incident":False,"unresolved_reliability":True})
 blocked("guardian_reliability_state",guardian={"unresolved_reliability":"unknown"})
 blocked("guardian_severity_blocks_maintenance",guardian={"severity_level":"unknown"})
 # Eligibility disappears immediately before mutation: fail closed.
 assert recheck_before_mutation(snap(session={"locked":False,"idle_seconds":0,"recent_input_seconds":0})).eligible is False
 critical=snap(maintenance={"in_critical_section":True,"interruption_safe":False})
 a=assess_maintenance(critical); assert not a.eligible and a.must_finish_bounded_critical_section
 assert maintenance_proposals(critical,created_at=NOW)==()
 print("ALL ADAPTIVE MAINTENANCE TESTS PASS")
if __name__=="__main__":main()
