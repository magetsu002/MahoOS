#!/usr/bin/env python3
import json, os, stat, tempfile
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"lib"))
from guardian_handoff import build_evidence_record,preserve_evidence,handoff_summary

def check(n,c):
    if not c: raise AssertionError(n)
    print("PASS",n)
obs={
 "incident_identity":{"id":"inc-test"},"boot_id":"boot-1","kernel_identity":{"release":"test"},
 "runtime_identity":{"generation":"g1"},"root_filesystem_identity":{"uuid":"root"},
 "recovery_generation_evidence":[{"id":"r1","coherent":False}],
 "active_high_severity_signals":[{"class":"kernel","status":"compromised"}],
 "process_metadata":[{"pid":1,"name":"init","cmdline":"runner --auth sk-supersecretvalue","environment":{"TOKEN":"nope"}}]*40,
 "password":"must-not-collect","browser_cookies":["nope"],
 "network_evidence":{"result":"observed","api_token":"must-not-persist","note":"Bearer abcdefghijklmnop","listeners":[{"address":"0.0.0.0","port":4444,"pid":9,"exe":"/tmp/demo","cmdline":"--token=secret"}]},
}
dec={"untrusted_boundaries":["kernel"],"trusted_boundaries":["personal-data-scope"],"catastrophic_reasons":["kernel lost"],"safe_actions":["preserve-evidence"],"unsafe_actions":["generic-shell-mutation"],"recovery_handoff":["offline-inspection"]}
record=build_evidence_record(obs,dec)
check("top-level secrets are not collected","password" not in record and "browser_cookies" not in record)
check("nested secret-like fields are omitted","api_token" not in record["network_evidence"])
check("process evidence is bounded",len(record["process_metadata"])==24)
check("raw process argv/environment are never preserved","cmdline" not in record["process_metadata"][0] and "environment" not in record["process_metadata"][0])
check("network evidence uses an explicit schema","api_token" not in record["network_evidence"] and "note" not in record["network_evidence"] and "cmdline" not in record["network_evidence"]["listeners"][0])
with tempfile.TemporaryDirectory() as td:
    path=Path(td)/"private"/"incident.json"; preserve_evidence(path,record)
    check("durable evidence written",json.loads(path.read_text())["incident_identity"]["id"]=="inc-test")
    check("evidence directory private",stat.S_IMODE(path.parent.stat().st_mode)==0o700)
    check("evidence file private",stat.S_IMODE(path.stat().st_mode)==0o600)
summary=handoff_summary(dec,"/state/inc.json")
check("handoff never claims mutation",summary["host_mutation_performed"] is False and summary["automatic_recovery_allowed"] is False)
check("handoff preserves explicit trust boundaries",summary["untrusted_boundaries"]==["kernel"])
print("ALL GUARDIAN G4 HANDOFF TESTS PASS")
