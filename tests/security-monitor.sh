#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_PACMAN_DB_ROOT="$TMP/pacman-local"
export MAHO_FS_ROOT="$TMP/fs"
export MAHO_PROC_ROOT="$TMP/proc"
export MAHO_SECURITY_INTEGRITY_INTERVAL=999999

DB="$MAHO_PACMAN_DB_ROOT"
FS="$MAHO_FS_ROOT"
PROC="$MAHO_PROC_ROOT"
STATE="$XDG_STATE_HOME/maho/security"
MONITOR="$ROOT/bin/maho-security-monitor"
PROBE="$ROOT/lib/security_probe.py"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$DB/alpha-1.0-1" "$FS/tmp" "$PROC"

write_alpha() {
    local version="$1"
    rm -rf "$DB"/alpha-*
    mkdir -p "$DB/alpha-$version"
    cat > "$DB/alpha-$version/desc" <<EOF_DESC
%NAME%
alpha

%VERSION%
$version

%ARCH%
x86_64

EOF_DESC
}

write_alpha 1.0-1
source "$ROOT/lib/events.sh"

count_kind() {
    local kind="$1"
    python - "$MAHO_EVENT_LOG" "$kind" <<'PY'
import json,sys
from pathlib import Path
path=Path(sys.argv[1]); kind=sys.argv[2]; count=0
if path.is_file():
    for line in path.read_text().splitlines():
        try: row=json.loads(line)
        except Exception: continue
        if row.get("version") == 1 and row.get("kind") == kind: count += 1
print(count)
PY
}

echo "=== first package observation captures evidence but not trust ==="
bash "$MONITOR" cycle
SNAPDIR="$STATE/provenance/snapshots"
[ "$(find "$SNAPDIR" -maxdepth 1 -type f -name '*.json' | wc -l)" -eq 1 ]
[ ! -e "$STATE/provenance/baseline.json" ]
[ "$(stat -c '%a' "$STATE/monitor-v2")" = 700 ]
[ "$(stat -c '%a' "$STATE/monitor-v2/packages.json")" = 600 ]
echo "PASS"

echo "=== identical package state is quiet ==="
bash "$MONITOR" cycle
[ "$(find "$SNAPDIR" -maxdepth 1 -type f -name '*.json' | wc -l)" -eq 1 ]
echo "PASS"

echo "=== package transition captures a new untrusted snapshot once ==="
write_alpha 1.1-1
BEFORE="$(count_kind packages.state-transition)"
bash "$MONITOR" cycle
AFTER="$(count_kind packages.state-transition)"
[ "$AFTER" -eq $((BEFORE + 1)) ]
[ "$(find "$SNAPDIR" -maxdepth 1 -type f -name '*.json' | wc -l)" -eq 2 ]
bash "$MONITOR" cycle
[ "$(count_kind packages.state-transition)" -eq "$AFTER" ]
[ "$(find "$SNAPDIR" -maxdepth 1 -type f -name '*.json' | wc -l)" -eq 2 ]
echo "PASS"

echo "=== persistence drift and recovery are transition-aware ==="
mkdir -p "$XDG_CONFIG_HOME/autostart"
printf '[Desktop Entry]\nType=Application\nName=Known\nExec=true\n' > "$XDG_CONFIG_HOME/autostart/known.desktop"
python "$PROBE" persistence snapshot --state-root "$STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$FS" >/dev/null
python "$PROBE" persistence baseline-set latest --state-root "$STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$FS" >/dev/null
# Let the monitor learn the clean baseline state first.
bash "$MONITOR" cycle
printf '[Desktop Entry]\nType=Application\nName=New\nExec=true\n' > "$XDG_CONFIG_HOME/autostart/new.desktop"
BEFORE="$(count_kind persistence.changed)"
bash "$MONITOR" cycle
AFTER="$(count_kind persistence.changed)"
[ "$AFTER" -eq $((BEFORE + 1)) ]
bash "$MONITOR" cycle
[ "$(count_kind persistence.changed)" -eq "$AFTER" ]
rm -f "$XDG_CONFIG_HOME/autostart/new.desktop"
BEFORE="$(count_kind persistence.restored)"
bash "$MONITOR" cycle
AFTER="$(count_kind persistence.restored)"
[ "$AFTER" -eq $((BEFORE + 1)) ]
echo "PASS"

echo "=== runtime signal and clearance are transition-aware ==="
mkdir -p "$PROC/222"
ln -s "$FS/tmp/dropper (deleted)" "$PROC/222/exe"
cat > "$PROC/222/status" <<EOF_STATUS
Name:\tdropper
State:\tS (sleeping)
Uid:\t$(id -u)\t$(id -u)\t$(id -u)\t$(id -u)
EOF_STATUS
printf 'dropper\0' > "$PROC/222/cmdline"
BEFORE="$(count_kind runtime.executable-observation)"
bash "$MONITOR" cycle
AFTER="$(count_kind runtime.executable-observation)"
[ "$AFTER" -eq $((BEFORE + 1)) ]
bash "$MONITOR" cycle
[ "$(count_kind runtime.executable-observation)" -eq "$AFTER" ]
rm -rf "$PROC/222"
BEFORE="$(count_kind runtime.executable-cleared)"
bash "$MONITOR" cycle
AFTER="$(count_kind runtime.executable-cleared)"
[ "$AFTER" -eq $((BEFORE + 1)) ]
echo "PASS"

echo "=== monitor doctor remains non-mutating by contract ==="
DOCTOR="$(bash "$MONITOR" doctor)"
grep -q 'automatic system mutation: none' <<< "$DOCTOR"
grep -q 'package state: captures untrusted evidence snapshots on change' <<< "$DOCTOR"
grep -q 'incident correlation:' <<< "$DOCTOR"
echo "PASS"

echo "ALL SECURITY MONITOR CONTRACTS PASS"
