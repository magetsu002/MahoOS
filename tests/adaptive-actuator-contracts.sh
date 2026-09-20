#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
STATE="$TMP/quiet"
FAKE_NOTIFY="$TMP/maho-notify"
printf '%s\n' off >"$STATE"

cat >"$FAKE_NOTIFY" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
state="${MAHO_TEST_NOTIFY_STATE:?}"
[ "${1:-}" = adaptive-quiet ] || exit 2
case "${2:-}" in
  status) cat "$state" ;;
  on|off) printf '%s\n' "$2" >"$state"; printf '%s\n' "$2" ;;
  *) exit 2 ;;
esac
EOF
chmod +x "$FAKE_NOTIFY"
export MAHO_ROOT="$ROOT"
export MAHO_NOTIFY_BIN="$FAKE_NOTIFY"
export MAHO_TEST_NOTIFY_STATE="$STATE"
export XDG_STATE_HOME="$TMP/state"
export MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH="$TMP/state/maho/adaptive/maintenance-veto.json"
source "$ROOT/lib/decision.sh"
fail() { echo "FAIL: $*" >&2; exit 1; }
execute() { bash "$ROOT/bin/maho-adapt" execute "$1"; }

decision() {
  maho_decision_create adaptive adaptive.a15.notifications adapt \
    notifications.presentation.adaptive-quiet \
    'certified A15 notification presentation lease' \
    '{"lease_ids":["lease-test"],"certified_effect":"notifications"}' \
    "{\"operation\":\"set-adaptive-notify-quiet\",\"enabled\":$1}"
}

echo '=== registry and ownership ==='
bash "$ROOT/bin/maho-adapt" validate-registry | grep -qx PASS
python - "$ROOT/config/ownership.json" <<'PY'
import json,sys
p=json.load(open(sys.argv[1]))
assert p["resources"]["notifications.presentation.adaptive-quiet"] == "maho"
assert p["resources"]["updates.maintenance.adaptive-veto"] == "maho"
PY
echo PASS
echo '=== verified mutation ==='
RESULT="$(execute "$(decision true)")"
[ "$(cat "$STATE")" = on ] || fail 'adaptive quiet did not turn on'
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "verified"
assert r["resource"] == "notifications.presentation.adaptive-quiet"
assert r["desired"]["enabled"] is True
assert r["before"]["enabled"] is False
'
echo PASS

echo '=== already satisfied is a no-op ==='
BEFORE="$(sha256sum "$STATE" | cut -d' ' -f1)"
RESULT="$(execute "$(decision true)")"
AFTER="$(sha256sum "$STATE" | cut -d' ' -f1)"
[ "$BEFORE" = "$AFTER" ] || fail 'already-satisfied actuator rewrote state'
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "verified" and r["action"] == "adapt"
assert "already verified" in r["reason"]
'
echo PASS

maintenance_desired() {
  python - "$1" <<'PY'
from datetime import datetime,timedelta,timezone
import json,sys
active=sys.argv[1] == "true"
desired={"operation":"set-adaptive-maintenance-veto","active":active}
if active:
 now=datetime.now(timezone.utc)
 stamp=lambda value:value.isoformat(timespec="milliseconds").replace("+00:00","Z")
 desired["state"]={
  "schema_version":1,"kind":"maho-adaptive-maintenance-veto","active":True,
  "lease_id":"lease-"+"1"*20,"effect":"maintenance","value":"suspended",
  "source_policy":"gaming.foreground","source_proposal_id":"prop-"+"2"*20,
  "captured_at":stamp(now-timedelta(seconds=30)),"updated_at":stamp(now),
  "valid_until":stamp(now+timedelta(seconds=120)),
 }
print(json.dumps(desired,sort_keys=True,separators=(",",":")))
PY
}

maintenance_decision() {
  maho_decision_create adaptive adaptive.a16.maintenance-veto adapt \
    updates.maintenance.adaptive-veto \
    'certified bounded Adaptive maintenance veto lease' \
    '{"lease_ids":["lease-11111111111111111111"],"certified_effect":"maintenance"}' \
    "$(maintenance_desired "$1")"
}

echo '=== verified maintenance veto and restoration ==='
RESULT="$(execute "$(maintenance_decision true)")"
[ -f "$MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH" ] || fail 'maintenance veto was not created'
[ "$(stat -c %a "$MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH")" = 600 ] || fail 'maintenance veto is not private'
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "verified"
assert r["resource"] == "updates.maintenance.adaptive-veto"
assert r["desired"]["active"] is True
assert r["before"]["present"] is False
'
RESULT="$(execute "$(maintenance_decision false)")"
[ ! -e "$MAHO_ADAPTIVE_MAINTENANCE_VETO_PATH" ] || fail 'lease expiry did not remove maintenance veto'
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "verified"
assert r["desired"] == {"operation":"set-adaptive-maintenance-veto","active":False}
assert r["before"]["present"] is True
'
echo PASS
echo '=== verify failure rolls back captured state ==='
printf '%s\n' off >"$STATE"
cat >"$FAKE_NOTIFY" <<'EOF_FAIL'
#!/usr/bin/env bash
set -euo pipefail
state="${MAHO_TEST_NOTIFY_STATE:?}"
[ "${1:-}" = adaptive-quiet ] || exit 2
case "${2:-}" in
  status) cat "$state" ;;
  on)
    if [ "${MAHO_TEST_NOTIFY_BREAK_ON:-0}" = 1 ]; then printf '%s\n' off >"$state"; else printf '%s\n' on >"$state"; fi
    printf '%s\n' on ;;
  off) printf '%s\n' off >"$state"; printf '%s\n' off ;;
  *) exit 2 ;;
esac
EOF_FAIL
chmod +x "$FAKE_NOTIFY"
export MAHO_TEST_NOTIFY_BREAK_ON=1
if execute "$(decision true)" >/dev/null 2>&1; then
  fail 'verification failure was accepted'
fi
[ "$(cat "$STATE")" = off ] || fail 'failed actuator did not roll back'
unset MAHO_TEST_NOTIFY_BREAK_ON
echo PASS

echo 'ALL ADAPTIVE ACTUATOR SHELL CONTRACTS PASS'
