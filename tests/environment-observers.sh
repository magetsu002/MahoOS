#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_SYSFS_ROOT="$TMP/sys"

mkdir -p \
    "$HOME" \
    "$XDG_STATE_HOME" \
    "$XDG_CONFIG_HOME" \
    "$MAHO_SYSFS_ROOT/class/power_supply/AC" \
    "$MAHO_SYSFS_ROOT/class/power_supply/BAT0" \
    "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0" \
    "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0"

printf 'Mains\n' > "$MAHO_SYSFS_ROOT/class/power_supply/AC/type"
printf '1\n' > "$MAHO_SYSFS_ROOT/class/power_supply/AC/online"
printf 'Battery\n' > "$MAHO_SYSFS_ROOT/class/power_supply/BAT0/type"
printf '83\n' > "$MAHO_SYSFS_ROOT/class/power_supply/BAT0/capacity"
printf 'Discharging\n' > "$MAHO_SYSFS_ROOT/class/power_supply/BAT0/status"
printf '1\n' > "$MAHO_SYSFS_ROOT/class/power_supply/BAT0/present"
printf 'x86_pkg_temp\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/type"
printf '62100\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf 'coretemp\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/name"
printf '61700\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
printf 'Package id 0\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_label"

source "$ROOT/lib/state.sh"
source "$ROOT/lib/events.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

event_count() {
    maho_event_tail 100 | grep -c 'thermal.changed' || true
}

last_thermal() {
    maho_event_last thermal
}

echo "=== current normalization ==="
bash "$ROOT/bin/maho-observe" current power | python -c '
import json,sys
p=json.load(sys.stdin)
bat=next(x for x in p["supplies"] if x["type"]=="Battery")
ac=next(x for x in p["supplies"] if x["type"]=="Mains")
assert bat["capacity_percent"] == 83
assert bat["capacity_bucket_percent"] == 80
assert bat["status"] == "Discharging"
assert ac["online"] is True
'
bash "$ROOT/bin/maho-observe" current thermal | python -c '
import json,sys
t=json.load(sys.stdin)
assert t["max_millidegree_c"] == 62100
assert t["max_bucket_millidegree_c"] == 60000
assert len(t["readings"]) == 2
'
echo "PASS"

echo "=== first observation publishes normal context ==="
bash "$ROOT/bin/maho-observe" once all
maho_state_get power >/dev/null
maho_state_get thermal >/dev/null
[ "$(maho_event_tail 20 | grep -c 'power.changed')" -eq 1 ] || fail "expected one power event"
[ "$(event_count)" -eq 1 ] || fail "expected one thermal event"
last_thermal | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["details"]["transition"]["level"] == "normal"
assert e["details"]["transition"]["reason"] == "initial"
'
echo "PASS"

echo "=== ordinary CPU jitter stays quiet but state refreshes ==="
printf '64900\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '64800\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(event_count)" -eq 1 ] || fail "normal thermal jitter emitted another event"
maho_state_get thermal | python -c '
import json,sys
s=json.load(sys.stdin)
assert s["data"]["max_millidegree_c"] == 64900
'
printf '70100\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '70000\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(event_count)" -eq 1 ] || fail "70 C boundary chatter emitted an event"
echo "PASS"

echo "=== entering warm context emits one event ==="
printf '75100\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '74800\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(event_count)" -eq 2 ] || fail "warm transition was not observed"
last_thermal | python -c '
import json,sys
e=json.load(sys.stdin); t=e["details"]["transition"]
assert t["previous_level"] == "normal"
assert t["level"] == "warm"
assert t["reason"] == "level-transition"
'
echo "PASS"

echo "=== downward hysteresis prevents warm chatter ==="
printf '72100\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '71800\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(event_count)" -eq 2 ] || fail "warm context dropped without crossing hysteresis release"
printf '69900\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '69800\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(event_count)" -eq 3 ] || fail "normal re-entry after hysteresis was not observed"
echo "PASS"

echo "=== direct jump to hot context is observed ==="
printf '85100\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '84800\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(event_count)" -eq 4 ] || fail "hot transition was not observed"
last_thermal | python -c '
import json,sys
e=json.load(sys.stdin); t=e["details"]["transition"]
assert t["level"] == "hot"
'
echo "PASS"

echo "=== concurrent observations dedupe ==="
rm -f "$XDG_STATE_HOME/maho/observer/thermal.reference.json"
BEFORE="$(event_count)"
bash "$ROOT/bin/maho-observe" once thermal &
P1=$!
bash "$ROOT/bin/maho-observe" once thermal &
P2=$!
wait "$P1"
wait "$P2"
AFTER="$(event_count)"
[ "$AFTER" -eq $((BEFORE + 1)) ] || fail "concurrent observers emitted duplicate thermal events"
echo "PASS"

echo "=== sensor topology change emits event ==="
printf 'Extra sensor\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp2_label"
printf '85100\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp2_input"
BEFORE="$(event_count)"
bash "$ROOT/bin/maho-observe" once thermal
AFTER="$(event_count)"
[ "$AFTER" -eq $((BEFORE + 1)) ] || fail "sensor topology change was not observed"
last_thermal | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["details"]["transition"]["reason"] == "topology-change"
'
echo "PASS"

echo "=== missing capability is non-fatal ==="
rm -rf "$MAHO_SYSFS_ROOT/class/power_supply" "$MAHO_SYSFS_ROOT/class/thermal" "$MAHO_SYSFS_ROOT/class/hwmon"
bash "$ROOT/bin/maho-observe" once all
bash "$ROOT/bin/maho-observe" doctor >/dev/null
echo "PASS"

echo "ALL ENVIRONMENT OBSERVER CONTRACTS PASS"
