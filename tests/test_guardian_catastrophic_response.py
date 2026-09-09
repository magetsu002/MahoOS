#!/usr/bin/env python3
import json,tempfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"lib"))
from guardian_catastrophic_response import prepare_catastrophic_response

def check(n,c):
    if not c: raise AssertionError(n)
    print("PASS",n)
state={"incident":{"scope":"boot","ownership":"maho","impact":"unavailable","evidence_confidence":"confirmed","persistent":True},"catastrophic":{"signals":[{"class":"boot","status":"corrupt","confidence":"confirmed"}],"recovery_state_known":True,"trusted_boundaries":["personal-data-scope"],"handoff_availability":{"offline_inspection":True}}}
recovery={"failure":{"domain":"kernel"},"availability":{"lts_kernel":False}}
obs={"incident_identity":{"id":"inc-g4"},"boot_id":"boot-test","kernel_identity":{"release":"test"},"active_high_severity_signals":[{"class":"boot"}]}
with tempfile.TemporaryDirectory() as td:
    p=Path(td)/"guardian"/"catastrophic"/"inc-g4.json"
    r=prepare_catastrophic_response(state,recovery,obs,p)
    check("real L4 preserves evidence before handoff",r.evidence_preserved and p.is_file())
    check("response performs no host mutation",not r.mutation_performed and not r.decision["mutating_recovery_allowed"])
    check("only proven handoff is advertised",r.handoff["recovery_handoff"]==["offline-inspection"])
    check("evidence contains incident identity",json.loads(p.read_text())["incident_identity"]["id"]=="inc-g4")
with tempfile.TemporaryDirectory() as td:
    safe={"incident":{"scope":"runtime","ownership":"maho","impact":"degraded","evidence_confidence":"high","persistent":True},"recovery":{"confidence":"certified","certified_path":True},"catastrophic":{"signals":[],"recovery_state_known":True}}
    r=prepare_catastrophic_response(safe,{"failure":{"domain":"maho-runtime","transaction_in_progress":True},"availability":{"previous_runtime_verified":True}},obs,Path(td)/"no.json")
    check("lower certified recovery produces no catastrophic handoff evidence",not r.evidence_preserved and r.handoff is None)
print("ALL GUARDIAN G4 RESPONSE TESTS PASS")
