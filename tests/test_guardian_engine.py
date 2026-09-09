#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lib"))

from guardian_engine import evaluate_guardian

def check(name, cond):
    if not cond: raise AssertionError(name)
    print("PASS",name)

def g(level_case, recovery):
    return evaluate_guardian(level_case, recovery)

safe_restart={
    "failure":{"domain":"service","graphical_available":True},
    "service":{"name":"maho-notify.service","consecutive_failures":1,"restart_safe":True},
}
l1={"incident":{"scope":"component","ownership":"maho","impact":"minor","evidence_confidence":"medium","occurrence_count":1}}
r=g(l1,safe_restart)
check("L1 Maho-owned recovery is delegated without Guardian mutation", r.severity["level"]==1 and r.execution_mode=="delegated" and not r.mutating_recovery_allowed)

l2_uncert={"incident":{"scope":"component","ownership":"maho","impact":"degraded","evidence_confidence":"high","persistent":True},"recovery":{"confidence":"high","certified_path":False}}
r=g(l2_uncert,safe_restart)
check("L2 delegated provider remains non-mutating",r.severity["level"]==2 and r.execution_mode=="delegated" and not r.mutating_recovery_allowed)

l2_cert={"incident":{"scope":"component","ownership":"maho","impact":"degraded","evidence_confidence":"high","persistent":True},"recovery":{"confidence":"certified","certified_path":True}}
r=g(l2_cert,safe_restart)
check("L2 certified provider still does not grant Guardian mutation",r.severity["level"]==2 and r.execution_mode=="delegated" and not r.mutating_recovery_allowed)

runtime_auto={
    "failure":{"domain":"maho-runtime","domain_confidence":"confirmed","transaction_in_progress":True,"graphical_available":True},
    "availability":{"previous_runtime_verified":True},
}
l2_runtime={"incident":{"scope":"runtime","ownership":"maho","impact":"degraded","evidence_confidence":"confirmed","persistent":True},"recovery":{"confidence":"certified","certified_path":True}}
r=g(l2_runtime,runtime_auto)
check("certified in-transaction Maho runtime recovery is a real L2 automatic path",r.severity["level"]==2 and r.execution_mode=="automatic" and r.mutating_recovery_allowed)
check("L2 runtime automatic path is the transactional Maho provider",r.recovery["action"]=="rollback-previous" and r.recovery["provider"]=="maho-runtime" and r.recovery["recovery_mode"]=="transactional")

runtime_post_transaction={
    "failure":{"domain":"maho-runtime","domain_confidence":"confirmed","transaction_in_progress":False,"graphical_available":True},
    "availability":{"previous_runtime_verified":True},
}
r=g(l2_runtime,runtime_post_transaction)
check("same L2 runtime failure outside activation remains confirmation gated",r.severity["level"]==2 and r.execution_mode=="confirm" and not r.mutating_recovery_allowed)

runtime_uncertain={
    "failure":{"domain":"maho-runtime","domain_confidence":"medium","transaction_in_progress":True,"graphical_available":True},
    "availability":{"previous_runtime_verified":True},
}
r=g(l2_runtime,runtime_uncertain)
check("unconfirmed L2 runtime domain never grants mutation",r.severity["level"]==2 and r.execution_mode=="diagnose" and not r.mutating_recovery_allowed)

l3_uncert={"incident":{"scope":"runtime","ownership":"maho","impact":"unavailable","evidence_confidence":"confirmed","persistent":True,"correlated_failures":2},"recovery":{"confidence":"high","certified_path":False,"previous_failures":1}}
r=g(l3_uncert,runtime_auto)
check("L3 remains L3 but asks when path is uncertified",r.severity["level"]==3 and r.execution_mode=="confirm" and not r.mutating_recovery_allowed)

l3_cert={"incident":{"scope":"runtime","ownership":"maho","impact":"unavailable","evidence_confidence":"confirmed","persistent":True,"correlated_failures":2},"recovery":{"confidence":"certified","certified_path":True,"previous_failures":1}}
r=g(l3_cert,runtime_auto)
check("L3 certified in-transaction rollback may remain automatic",r.severity["level"]==3 and r.execution_mode=="automatic" and r.mutating_recovery_allowed)

l4={"incident":{"scope":"boot","ownership":"maho","impact":"catastrophic","evidence_confidence":"confirmed","persistent":True},"recovery":{"confidence":"certified","certified_path":True}}
kernel={"failure":{"domain":"kernel"},"availability":{"lts_kernel":True}}
r=g(l4,kernel)
check("L4 always hands off",r.severity["level"]==4 and r.execution_mode=="handoff" and not r.mutating_recovery_allowed)

diag=g({"incident":{"scope":"component","ownership":"unknown","impact":"minor","occurrence_count":1}}, {"failure":{"domain":"unknown","graphical_available":True}})
check("unknown recovery domain remains non-mutating diagnosis",diag.execution_mode=="diagnose" and not diag.mutating_recovery_allowed)

print("ALL GUARDIAN ENGINE TESTS PASS")
