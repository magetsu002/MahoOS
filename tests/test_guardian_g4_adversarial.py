#!/usr/bin/env python3
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lib"))
from guardian_catastrophic import assess_catastrophic, preview_catastrophic_mutation

def check(n,c):
    if not c: raise AssertionError(n)
    print("PASS",n)

def sig(c,s,confidence="confirmed"):
    return {"class":c,"status":s,"confidence":confidence}

modules=[ROOT/"lib/guardian_catastrophic.py",ROOT/"lib/guardian_handoff.py",ROOT/"lib/guardian_catastrophic_response.py"]
text="\n".join(p.read_text() for p in modules)
for forbidden in ("subprocess", "os.system", "Popen(", "shell=True", "while True", "rm -rf", "kill("):
    check(f"G4 source contains no executor primitive: {forbidden}",forbidden not in text)

# A large pile of one observation class remains one class.
r=assess_catastrophic({"signals":[sig("package-integrity","corrupt") for _ in range(1000)],"recovery_state_known":True})
check("1000 duplicate integrity reports are not qualitative L4",not r.catastrophic)

# Unknown is refusal/diagnosis, not invented catastrophe.
r=assess_catastrophic({"signals":[{"class":"boot","status":"unknown","confidence":"confirmed"}],"recovery_state_known":False})
check("unknown boot/recovery evidence fails closed without L4",not r.catastrophic and r.fail_closed)

# A certified lower recovery remains authoritative when its trust boundary is intact.
r=assess_catastrophic({"signals":[sig("root-filesystem","corrupt")],"recovery_state_known":True,"lower_layer_recovery":{"level":3,"available":True,"certified":True,"trusted":True}})
check("trusted L3 path prevents unnecessary catastrophic handoff",not r.catastrophic and not r.recovery_handoff)

# Never advertise an unproved recovery environment/LTS path.
r=assess_catastrophic({"signals":[sig("kernel","compromised")],"recovery_state_known":True,"handoff_availability":{"offline_inspection":True,"recovery_environment":False,"lts_kernel":False}})
check("handoff cannot invent LTS or recovery environment",r.recovery_handoff==("offline-inspection",))

# Destruction preview is an authority decision only.
r=preview_catastrophic_mutation({"requested_scope":"system","root_affected":True,"boot_affected":True,"personal_data_scope":"unknown","recovery_state_available":False,"operation_reversible":False,"provider_certified":False,"handoff_availability":{"power_down":True}})
check("catastrophic destructive request is prevented before execution",r.catastrophic and r.prevented and not r.host_mutation_performed)
check("destruction preview still only offers proven handoff",r.recovery_handoff==("power-down-and-investigate",))

# Compromised recovery authority cannot self-certify a live repair.
r=assess_catastrophic({"signals":[sig("security-provider","compromised")],"recovery_state_known":True,"lower_layer_recovery":{"level":3,"available":True,"certified":True,"trusted":True}})
check("compromised recovery provider overrides apparent lower-layer availability",r.catastrophic and "security-provider" in r.untrusted_boundaries)

check("catastrophic state always bans generic mutation","generic-shell-mutation" in r.unsafe_actions and not r.automatic_host_mutation_allowed)
print("ALL GUARDIAN G4 ADVERSARIAL CONTRACTS PASS")
