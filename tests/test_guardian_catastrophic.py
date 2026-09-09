#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lib"))
from guardian_catastrophic import assess_catastrophic, preview_catastrophic_mutation

def sig(cls,status,confidence="confirmed"):
    return {"class":cls,"status":status,"confidence":confidence}
def check(name, cond):
    if not cond: raise AssertionError(name)
    print("PASS",name)
def assess(signals, lower=None, **extra):
    return assess_catastrophic(
        {"signals": signals, "recovery_state_known": True, **extra},
        lower_layer_recovery=lower,
    )

r=assess([sig("kernel","compromised")]); check("confirmed kernel compromise reaches L4",r.catastrophic and r.severity==4)
r=assess([sig("boot","corrupt")]); check("confirmed boot corruption reaches L4",r.catastrophic)
r=assess([sig("root-filesystem","corrupt"),sig("recovery-state","unavailable")]); check("root corruption without coherent recovery reaches L4",r.catastrophic)
r=assess([sig("runtime","verification-failed"),sig("recovery-state","invalid")]); check("bad runtime plus invalid previous recovery reaches L4",r.catastrophic)
r=assess([sig("recovery-state","contradictory")]); check("recovery provider contradiction reaches L4",r.catastrophic)
r=assess([sig("privilege-boundary","compromised"),sig("package-integrity","corrupt"),sig("persistence","compromised")]); check("independent security authorities corroborate L4",r.catastrophic)
r=assess([sig("privilege-boundary","compromised")]*100); check("duplicates from one evidence class do not inflate to L4",not r.catastrophic)
r=assess([sig("kernel","compromised","low")]); check("low-confidence catastrophic-looking evidence is not L4",not r.catastrophic)
r=assess_catastrophic({"signals":[],"recovery_state_known":False}); check("unknown recovery state fails closed without fabricated L4",not r.catastrophic and r.fail_closed and r.severity==0)
lower={"level":2,"available":True,"certified":True,"trusted":True}
r=assess([sig("root-filesystem","corrupt")],lower=lower); check("valid bounded L2 remains below L4",not r.catastrophic)
lower3={"level":3,"available":True,"certified":True,"trusted":True}
r=assess([sig("root-filesystem","corrupt")],lower=lower3); check("valid bounded L3 remains below L4",not r.catastrophic and r.terminal_state=="resolved-by-lower-layer")
r=assess([sig("kernel","compromised")],handoff_availability={"recovery_environment":True}); check("L4 never authorizes automatic recovery or mutation",not r.automatic_recovery_allowed and not r.automatic_host_mutation_allowed)
check("handoff options are evidence-backed",r.recovery_handoff==("boot-recovery-environment",))
check("L4 exposes no generic executor", "generic-shell-mutation" in r.unsafe_actions and r.host_mutation_performed is False)
r=assess_catastrophic({"guardian_health":{"runtime_consistent":False},"recovery_state_known":True}); check("Guardian self inconsistency degrades authority without self-certifying L4",not r.catastrophic and r.guardian_authority_degraded and r.fail_closed)
r=preview_catastrophic_mutation({"root_affected":True,"boot_affected":True,"personal_data_scope":"unknown","recovery_state_available":False,"operation_reversible":False,"provider_certified":False}); check("destructive preview denies execution without pretending recovery",r.catastrophic and r.prevented and not r.host_mutation_performed)
print("ALL GUARDIAN G4 CATASTROPHIC AUTHORITY TESTS PASS")
