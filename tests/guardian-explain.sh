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

OUT="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why)"
printf '%s\n' "$OUT"
grep -Fq 'The wheel is active because 2 incidents need attention. Highest severity: L2.' <<<"$OUT"
grep -Fq '[1/2] L2 component  service:maho-demo.service' <<<"$OUT"
grep -Fq '[2/2] L1 minor  host:local' <<<"$OUT"
grep -Fq 'What happened' <<<"$OUT"
grep -Fq 'What Maho is doing' <<<"$OUT"
grep -Fq 'What you should do' <<<"$OUT"
grep -Fq 'maho-demo.service stopped unexpectedly' <<<"$OUT"
grep -Fq '1 startup entry appeared' <<<"$OUT"
HIST="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why inc-runtime-demo)"
grep -Fq 'newly activated Maho runtime failed immutable-runtime verification' <<<"$HIST"
grep -Fq 'Verification failures: payload_content_identity_mismatch' <<<"$HIST"
grep -Fq 'Previous verified revision: good' <<<"$HIST"

rm -f "$STATE/guardian/active/"*.json
QUIET="$(XDG_STATE_HOME="$TMP/state" MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-guard" why)"
grep -Fq 'Guardian is quiet. No active assessment is driving the wheel.' <<<"$QUIET"

echo 'ALL GUARDIAN EXPLAIN CONTRACTS PASS'
