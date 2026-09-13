#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STATE="$TMP/state/maho/security"
mkdir -p "$STATE/guardian/active" "$STATE/guardian/archive" "$STATE/incidents/active"

python - "$STATE" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
def dump(path, data):
    path.write_text(json.dumps(data))

def decision(level, label, action, mode="diagnose"):
    return {"severity":{"level":level,"label":label},"execution_mode":mode,
            "mutating_recovery_allowed":False,
            "recovery":{"action":action,"automatic_allowed":True,
                        "requires_confirmation":False,"provider":"systemd-user"}}

service={"incident_id":"inc-service-demo","status":"active","opened_at":"2026-09-10T10:00:00Z",
         "subject":{"type":"service","id":"maho-demo.service"},"decision":decision(2,"component","observe-service-recovery","delegated"),
         "normalized":{"incident":{"evidence_confidence":"confirmed"}},
         "service_recovery":{"unit":"maho-demo.service","failure_result":"signal","lifecycle":"verifying",
         "postcondition":{"observed":{"active_state":"active","sub_state":"running","result":"success","health_ok":True}}}}
dump(root/"guardian/active/inc-service-demo.json",service)
PY
python - "$STATE" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
def dump(path, data): path.write_text(json.dumps(data))

def decision(level,label,action):
    return {"severity":{"level":level,"label":label},"execution_mode":"diagnose","mutating_recovery_allowed":False,
            "recovery":{"action":action,"automatic_allowed":True,"requires_confirmation":False}}

host={"incident_id":"inc-host-demo","status":"active","opened_at":"2026-09-10T11:00:00Z",
      "subject":{"type":"host","id":"local"},"decision":decision(1,"minor","diagnose-only"),
      "normalized":{"incident":{"evidence_confidence":"low"}}}
dump(root/"guardian/active/inc-host-demo.json",host)
security={"incident_id":"inc-host-demo","status":"active","confidence":"low",
          "signals":[{"kind":"persistence-drift","details":{"added":[{"path":"/etc/xdg/autostart/demo.desktop"}],"changed":[]}}]}
dump(root/"incidents/active/inc-host-demo.json",security)

runtime={"incident_id":"inc-runtime-demo","status":"resolved","opened_at":"2026-09-09T11:00:00Z",
         "subject":{"type":"runtime","id":"bad-runtime"},"decision":decision(0,"normal","rollback-previous"),
         "runtime_recovery":{"lifecycle":"recovered","failed_runtime":{"reasons":["payload_content_identity_mismatch"],"source_revision":"bad"},
         "replacement_runtime":{"source_revision":"good"},"transaction_id":"runtime-demo"}}
dump(root/"guardian/archive/inc-runtime-demo-resolved.json",runtime)
PY

python - "$STATE" <<'PY_MULTI'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
def dump(path,data): path.write_text(json.dumps(data))
def decision(level,label,action='diagnose-only',catastrophic=False):
    d={"severity":{"level":level,"label":label},"execution_mode":"diagnose","mutating_recovery_allowed":False,
       "recovery":{"action":action,"automatic_allowed":True,"requires_confirmation":False}}
    if catastrophic:
        d["catastrophic"]={"catastrophic":True,"fail_closed":True,"evidence_preservation_required":True}
    return d
def guardian(iid,subject,level,label,**extra):
    row={"incident_id":iid,"status":"active","opened_at":"2026-09-10T12:00:00Z","subject":subject,
         "decision":decision(level,label,catastrophic=extra.pop('catastrophic',False)),
         "normalized":{"incident":{"evidence_confidence":extra.pop('confidence','medium')}}}
    row.update(extra); dump(root/f"guardian/active/{iid}.json",row)
def security(iid,subject,signals,confidence='medium'):
    dump(root/f"incidents/active/{iid}.json",{"incident_id":iid,"status":"active","subject":subject,"confidence":confidence,"signals":signals})

guardian('inc-integrity-demo',{'type':'package','id':'alpha'},2,'component')
security('inc-integrity-demo',{'type':'package','id':'alpha'},[
    {'kind':'integrity-drift','details':{'count':2,'items':[{'class':'modified','path':'/usr/bin/alpha'},{'class':'missing','path':'/usr/lib/alpha.so'}]}}])
guardian('inc-privilege-demo',{'type':'host','id':'local'},3,'system')
security('inc-privilege-demo',{'type':'host','id':'local'},[
    {'kind':'privilege-boundary','details':{'added':[{'path':'/etc/sudoers.d/demo'}],'changed':[],'removed':[]}}])
guardian('inc-runtime-exec-demo',{'type':'host','id':'local'},1,'minor',confidence='low')
security('inc-runtime-exec-demo',{'type':'host','id':'local'},[
    {'kind':'runtime-executable','details':{'observations':[{'pid':4242,'exe':'/tmp/dropper (deleted)','signals':['deleted-executable']}]}}], 'low')
guardian('inc-finding-demo',{'type':'package','id':'alpha'},3,'component',confidence='confirmed')
security('inc-finding-demo',{'type':'package','id':'alpha'},[
    {'kind':'confirmed-finding','details':{'summary':'Alpha 1.0 is confirmed affected.','installed_version':'1.0','finding_id':'CVE-DEMO'}},
    {'kind':'affected-package-process','details':{'processes':[{'pid':99,'exe':'/usr/bin/alpha'}]}},
    {'kind':'network-exposure','details':{'listeners':[{'address':'0.0.0.0','port':8080,'pid':99,'name':'alpha'}]}}
], 'confirmed')
guardian('inc-l4-demo',{'type':'host','id':'local'},4,'catastrophic',catastrophic=True,confidence='confirmed')
PY_MULTI

for id in inc-integrity-demo inc-privilege-demo inc-runtime-exec-demo inc-finding-demo inc-l4-demo; do
  mv "$STATE/guardian/active/$id.json" "$TMP/$id.guardian.json"
  [ -f "$STATE/incidents/active/$id.json" ] && mv "$STATE/incidents/active/$id.json" "$TMP/$id.security.json"
done
OUT="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why)"
printf '%s\n' "$OUT"
grep -Fq '2 active incidents · highest L2' <<<"$OUT"
grep -Fq '[1/2] L2 component · service:maho-demo.service' <<<"$OUT"
grep -Fq '[2/2] L1 minor · host:local' <<<"$OUT"
grep -Fq 'Change    maho-demo.service stopped unexpectedly' <<<"$OUT"
grep -Fq 'Decision  systemd restart delegated; Guardian is verifying the replacement.' <<<"$OUT"
grep -Fq 'Next      ' <<<"$OUT"
grep -Fq '1 startup entry appeared' <<<"$OUT"
! grep -Fq 'Why Guardian cares' <<<"$OUT"
VERBOSE="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why --verbose)"
grep -Fq 'The wheel is active because 2 incidents need attention. Highest severity: L2.' <<<"$VERBOSE"
grep -Fq 'Why Guardian cares' <<<"$VERBOSE"
grep -Fq 'What Maho is doing' <<<"$VERBOSE"
grep -Fq 'What you should do' <<<"$VERBOSE"

for id in inc-integrity-demo inc-privilege-demo inc-runtime-exec-demo inc-finding-demo inc-l4-demo; do
  mv "$TMP/$id.guardian.json" "$STATE/guardian/active/$id.json"
  [ -f "$TMP/$id.security.json" ] && mv "$TMP/$id.security.json" "$STATE/incidents/active/$id.json"
done
INTEGRITY="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-integrity-demo)"
grep -Fq 'installed package file(s) differ from the package manifest' <<<"$INTEGRITY"
grep -Fq 'modified: /usr/bin/alpha' <<<"$INTEGRITY"
grep -Fq 'Compare the listed files with the owning package/update transaction' <<<"$INTEGRITY"
PRIV="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-privilege-demo)"
grep -Fq 'Privilege boundaries changed' <<<"$PRIV"
grep -Fq 'added: /etc/sudoers.d/demo' <<<"$PRIV"
grep -Fq 'Verify who changed the listed privileged paths' <<<"$PRIV"
RUNTIME_EXEC="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-runtime-exec-demo)"
grep -Fq '/tmp/dropper (deleted) (deleted-executable)' <<<"$RUNTIME_EXEC"
grep -Fq 'Guardian will not kill it automatically' <<<"$RUNTIME_EXEC"
FINDING="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-finding-demo)"
grep -Fq 'Alpha 1.0 is confirmed affected.' <<<"$FINDING"
grep -Fq 'Affected installed version: 1.0' <<<"$FINDING"
grep -Fq 'listener: 0.0.0.0:8080 pid=99 alpha' <<<"$FINDING"
grep -Fq 'containment or removal stays authority-gated' <<<"$FINDING"
L4="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-l4-demo)"
grep -Fq 'Fail-closed; preserve evidence and refuse unsafe automatic repair.' <<<"$L4"
grep -Fq 'Preserve evidence and use only a certified recovery path' <<<"$L4"

HIST="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-runtime-demo)"
grep -Fq 'newly activated Maho runtime failed immutable-runtime verification' <<<"$HIST"
grep -Fq 'Verification failures: payload_content_identity_mismatch' <<<"$HIST"
grep -Fq 'Previous verified revision: good' <<<"$HIST"

rm -f "$STATE/guardian/active/"*.json
QUIET="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why)"
grep -Fq 'Guardian is quiet. No active assessment is driving the wheel.' <<<"$QUIET"

echo 'ALL GUARDIAN EXPLAIN CONTRACTS PASS'
