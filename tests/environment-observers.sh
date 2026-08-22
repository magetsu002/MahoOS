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

echo "=== first observation publishes state ==="
bash "$ROOT/bin/maho-observe" once all
maho_state_get power >/dev/null
maho_state_get thermal >/dev/null
[ "$(maho_event_tail 20 | grep -c 'power.changed')" -eq 1 ] || fail "expected one power event"
[ "$(maho_event_tail 20 | grep -c 'thermal.changed')" -eq 1 ] || fail "expected one thermal event"
echo "PASS"

echo "=== same thermal band is quiet ==="
printf '62900\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
printf '62800\n' > "$MAHO_SYSFS_ROOT/class/hwmon/hwmon0/temp1_input"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(maho_event_tail 20 | grep -c 'thermal.changed')" -eq 1 ] || fail "sub-band thermal jitter emitted another event"
echo "PASS"

echo "=== crossing thermal band emits one event ==="
printf '65100\n' > "$MAHO_SYSFS_ROOT/class/thermal/thermal_zone0/temp"
bash "$ROOT/bin/maho-observe" once thermal
[ "$(maho_event_tail 20 | grep -c 'thermal.changed')" -eq 2 ] || fail "thermal band transition was not observed"
echo "PASS"

echo "=== concurrent observations dedupe ==="
rm -f "$XDG_STATE_HOME/maho/observer/thermal.signature"
BEFORE="$(maho_event_tail 100 | grep -c 'thermal.changed')"
bash "$ROOT/bin/maho-observe" once thermal &
P1=$!
bash "$ROOT/bin/maho-observe" once thermal &
P2=$!
wait "$P1"
wait "$P2"
AFTER="$(maho_event_tail 100 | grep -c 'thermal.changed')"
[ "$AFTER" -eq $((BEFORE + 1)) ] || fail "concurrent observers emitted duplicate thermal events"
echo "PASS"

echo "=== missing capability is non-fatal ==="
rm -rf "$MAHO_SYSFS_ROOT/class/power_supply" "$MAHO_SYSFS_ROOT/class/thermal" "$MAHO_SYSFS_ROOT/class/hwmon"
bash "$ROOT/bin/maho-observe" once all
bash "$ROOT/bin/maho-observe" doctor >/dev/null
echo "PASS"

echo "ALL ENVIRONMENT OBSERVER CONTRACTS PASS"
