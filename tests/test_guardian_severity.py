#!/usr/bin/env python3
from __future__ import annotations
import copy
import importlib.util
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
MODULE=ROOT/"lib"/"guardian_severity.py"
spec=importlib.util.spec_from_file_location("guardian_severity",MODULE)
if spec is None or spec.loader is None:
    raise SystemExit("unable to load guardian_severity")
guardian=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=guardian
spec.loader.exec_module(guardian)

def assess(*, incident=None, recovery=None, context=None):
    state={"incident":incident or {},"recovery":recovery or {},"context":context or {}}
    original=copy.deepcopy(state)
    result=guardian.assess_guardian(state)
    if state != original:
        raise AssertionError("severity policy mutated input")
    return result

def check(name, condition):
    if not condition: raise AssertionError(name)
    print("PASS",name)

def main():
    result=assess()
    check("empty normalized state remains L0",result.level==0 and not result.suppressed and not result.automatic_recovery_allowed)

    result=assess(incident={"scope":17,"ownership":True,"impact":"banana","occurrence_count":True},recovery={"confidence":4,"certified_path":"yes"})
    check("malformed input fails closed without inventing an incident",result.level==0 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"session","ownership":"maho","impact":"unavailable","evidence_confidence":"confirmed","persistent":True,"correlated_failures":4},
        recovery={"confidence":"certified","certified_path":True,"previous_failures":1},
        context={"maintenance":True},
    )
    check("maintenance suppresses escalation",result.level==0 and result.suppressed and not result.automatic_recovery_allowed)

    result=assess(incident={"scope":"component","ownership":"maho","impact":"minor","evidence_confidence":"medium","occurrence_count":1})
    check("L1 Maho-owned component anomaly permits automatic posture",result.level==1 and result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"component","ownership":"unknown","impact":"minor","evidence_confidence":"confirmed","occurrence_count":1},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("unknown ownership never authorizes mutation",result.level==1 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"component","ownership":"user","impact":"minor","evidence_confidence":"confirmed","occurrence_count":1},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("user ownership never authorizes mutation",result.level==1 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"component","ownership":"maho","impact":"degraded","evidence_confidence":"high","occurrence_count":99},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("repetition alone does not become severity policy",result.level==1 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"component","ownership":"maho","impact":"degraded","evidence_confidence":"high","persistent":True,"occurrence_count":4},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("persistent certified Maho component failure reaches automatic L2",result.level==2 and result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"runtime","ownership":"maho","impact":"degraded","evidence_confidence":"confirmed","persistent":True},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("certified Maho runtime failure reaches automatic L2 posture",result.level==2 and result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"runtime","ownership":"maho","impact":"degraded","evidence_confidence":"confirmed","persistent":True},
        recovery={"confidence":"high","certified_path":False},
    )
    check("uncertified runtime L2 never authorizes mutation",result.level==2 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"component","ownership":"maho","impact":"degraded","evidence_confidence":"low","persistent":True,"occurrence_count":9},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("low-confidence evidence cannot drive aggressive recovery",result.level==1 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"component","ownership":"unknown","impact":"degraded","evidence_confidence":"confirmed","persistent":True},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("unknown ownership may surface L2 but cannot automate",result.level==2 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"session","ownership":"maho","impact":"unavailable","evidence_confidence":"high","persistent":True,"correlated_failures":3},
        recovery={"confidence":"certified","certified_path":True,"previous_failures":1},
    )
    check("certified correlated session failure reaches automatic L3",result.level==3 and result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"session","ownership":"maho","impact":"unavailable","evidence_confidence":"confirmed","persistent":True,"correlated_failures":3},
        recovery={"confidence":"high","certified_path":False,"previous_failures":2},
    )
    check("uncertified broader path remains L3 but cannot automate",result.level==3 and not result.automatic_recovery_allowed and not result.recovery_handoff_required)

    result=assess(
        incident={"scope":"boot","ownership":"maho","impact":"catastrophic","evidence_confidence":"confirmed","persistent":True},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("L4 is explicit handoff only",result.level==4 and result.recovery_handoff_required and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"system","ownership":"maho","impact":"catastrophic","evidence_confidence":"low","persistent":True,"occurrence_count":8},
        recovery={"confidence":"certified","certified_path":True},
    )
    check("low-confidence catastrophic signal does not enter L4",result.level<4 and not result.automatic_recovery_allowed)

    result=assess(
        incident={"scope":"boot","ownership":"maho","impact":"catastrophic","evidence_confidence":"confirmed","persistent":True,"resolved":False},
        recovery={"confidence":"certified","certified_path":True,"verified":True},
    )
    check("stale verified flag cannot hide active catastrophic evidence",result.level==4 and result.recovery_handoff_required)

    result=assess(
        incident={"scope":"session","ownership":"maho","impact":"unavailable","evidence_confidence":"confirmed","persistent":True,"correlated_failures":5,"resolved":True},
        recovery={"confidence":"certified","certified_path":True,"previous_failures":2,"verified":True},
    )
    check("verified resolved recovery de-escalates to normal",result.level==0 and not result.suppressed)

    check("severity output contains no concrete recovery action",not hasattr(result,"action") and "action" not in result.as_dict())
    print("ALL GUARDIAN SEVERITY POLICY TESTS PASS")

if __name__=="__main__":
    main()
