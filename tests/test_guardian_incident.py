#!/usr/bin/env python3
from __future__ import annotations
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lib"))

from guardian_incident import evaluate_security_incident, normalize_security_incident, reconcile_security

def check(name, condition):
    if not condition: raise AssertionError(name)
    print("PASS",name)

def incident(*, iid="inc-package-test", subject=None, risk="critical", confidence="confirmed", signals=None, status="active", source_diversity=3):
    return {
        "version":1,
        "kind":"security-incident",
        "incident_id":iid,
        "status":status,
        "subject":subject or {"type":"package","id":"alpha"},
        "risk":risk,
        "confidence":confidence,
        "source_diversity":source_diversity,
        "signals":signals or [
            {"kind":"confirmed-finding","source":"finding:test"},
            {"kind":"integrity-drift","source":"pacman-mtree"},
            {"kind":"runtime-executable","source":"procfs"},
        ],
        "opened_at":"2026-09-08T00:00:00Z",
        "updated_at":"2026-09-08T00:01:00Z",
    }

def main():
    third_party=incident()
    normalized=normalize_security_incident(third_party)
    check("third-party package remains unknown ownership",normalized["incident"]["ownership"]=="unknown")
    check("durable evidence marks semantic persistence",normalized["incident"]["persistent"] is True)
    result=evaluate_security_incident(third_party)
    check("real correlated package incident reaches L2 without authorizing mutation",result["decision"]["severity"]["level"]==2 and not result["decision"]["mutating_recovery_allowed"])
    check("security incident recovery remains diagnose-only",result["decision"]["recovery"]["action"]=="diagnose-only" and result["decision"]["execution_mode"]=="diagnose")

    maho_minor=incident(
        iid="inc-package-maho",
        subject={"type":"package","id":"maho-notify"},
        risk="low",
        confidence="high",
        signals=[{"kind":"runtime-executable","source":"procfs"}],
        source_diversity=1,
    )
    result=evaluate_security_incident(maho_minor)
    check("Maho package identity can carry L1 automatic posture",result["decision"]["severity"]["level"]==1 and result["decision"]["severity"]["automatic_recovery_allowed"])
    check("automatic posture still cannot invent a mutating security recovery",not result["decision"]["mutating_recovery_allowed"] and result["decision"]["recovery"]["action"]=="diagnose-only")

    host=incident(
        iid="inc-host-local",
        subject={"type":"host","id":"local"},
        risk="critical",
        confidence="confirmed",
        signals=[{"kind":"persistence-drift","source":"persistence-baseline"}],
        source_diversity=1,
    )
    result=evaluate_security_incident(host)
    check("confirmed catastrophic host incident is L4 handoff only",result["decision"]["severity"]["level"]==4 and result["decision"]["execution_mode"]=="handoff" and not result["decision"]["mutating_recovery_allowed"])

    repeated=incident(
        iid="inc-package-repeat",
        risk="high",
        confidence="high",
        signals=[{"kind":"runtime-executable","source":"procfs"}],
        source_diversity=1,
    )
    normalized=normalize_security_incident(repeated)
    check("transient repeated-runtime evidence is not falsely persistent",normalized["incident"]["persistent"] is False)

    resolved=incident(status="resolved")
    resolved["resolved_at"]="2026-09-08T00:02:00Z"
    result=evaluate_security_incident(resolved)
    check("cleared evidence de-escalates resolved record",result["decision"]["severity"]["level"]==0 and result["status"]=="resolved")

    with tempfile.TemporaryDirectory() as td:
        state=Path(td)
        created=incident()
        summary=reconcile_security(state,{"created":[created],"updated":[],"unchanged":[],"resolved":[]})
        active=state/"guardian"/"active"/f"{created['incident_id']}.json"
        check("active Guardian assessment is persisted",summary["active"]==1 and active.is_file())
        check("Guardian state permissions are private",oct(active.stat().st_mode & 0o777)=="0o600")
        cleared=dict(created); cleared["status"]="resolved"; cleared["resolved_at"]="2026-09-08T00:02:00Z"
        summary=reconcile_security(state,{"created":[],"updated":[],"unchanged":[],"resolved":[cleared]})
        archive=list((state/"guardian"/"archive").glob("*.json"))
        check("resolved Guardian assessment moves to history",summary["active"]==0 and not active.exists() and len(archive)==1)

    print("ALL GUARDIAN INCIDENT NORMALIZATION TESTS PASS")

if __name__=="__main__":
    main()
