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

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$DB/alpha-1.0-1" "$FS/tmp" "$PROC/sys/kernel/random"
printf '%s
' 'fixture-boot' > "$PROC/sys/kernel/random/boot_id"

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

echo "=== integrity throttle cannot suppress required provider freshness ==="
INTEGRITY_PROVIDER="$STATE/guardian/providers/security.integrity.json"
[ -s "$INTEGRITY_PROVIDER" ]
rm -f "$INTEGRITY_PROVIDER"
date +%s > "$STATE/monitor-v2/integrity-last-run"
bash "$MONITOR" cycle
[ -s "$INTEGRITY_PROVIDER" ]
python - "$INTEGRITY_PROVIDER" <<'PY_INTEGRITY_HEARTBEAT'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
assert value.get("provider_id") == "security.integrity"
assert value.get("last_attempt_at")
assert value.get("sequence") == 1
PY_INTEGRITY_HEARTBEAT
echo "PASS"

echo "=== integrity throttle cannot reuse a previous-boot heartbeat ==="
python - "$INTEGRITY_PROVIDER" <<'PY_STALE_BOOT'
import json,sys
from pathlib import Path
path=Path(sys.argv[1])
value=json.loads(path.read_text())
value["boot_id"]="previous-boot"
path.write_text(json.dumps(value,indent=2,sort_keys=True)+"\n")
PY_STALE_BOOT
date +%s > "$STATE/monitor-v2/integrity-last-run"
bash "$MONITOR" cycle
python - "$INTEGRITY_PROVIDER" <<'PY_CURRENT_BOOT'
import json,sys
from pathlib import Path
value=json.loads(Path(sys.argv[1]).read_text())
assert value.get("boot_id") == "fixture-boot"
assert value.get("sequence") == 2
PY_CURRENT_BOOT
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
PERSIST_SNAPSHOT="$(python "$PROBE" persistence snapshot --state-root "$STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$FS")"
PERSIST_STATE_SHA="$(printf '%s\n' "$PERSIST_SNAPSHOT" | python -c 'import json,sys; print(json.load(sys.stdin)["state_sha256"])')"
python "$PROBE" persistence baseline-set latest --accept-state "$PERSIST_STATE_SHA" --reason 'security-monitor fixture accepted state' --state-root "$STATE" --home "$HOME" --xdg-config "$XDG_CONFIG_HOME" --fs-root "$FS" >/dev/null
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

echo "=== verified Maho wiring is informational, not unexplained persistence ==="
DATA_HOME="$HOME/.local/share"
python - "$ROOT" "$DATA_HOME" <<'PY_MAHO_MONITOR'
import json, os, pathlib, sys
root=pathlib.Path(sys.argv[1]); data=pathlib.Path(sys.argv[2]); sys.path.insert(0,str(root/'lib'))
from maho_runtime_release import _payload_hash
runtime=data/'maho/runtime'; releases=runtime/'releases'; releases.mkdir(parents=True)
stage=releases/'.fixture'; (stage/'systemd/user').mkdir(parents=True); (stage/'share/maho').mkdir(parents=True)
(stage/'systemd/user/maho-adaptive.service').write_text('[Service]\nExecStart=true\n')
revision='b'*40; (stage/'share/maho/runtime-source-revision').write_text(revision+'\n')
digest=_payload_hash(stage); release=releases/digest; stage.rename(release)
(release/'manifest.json').write_text(json.dumps({'version':3,'content_sha256':digest,'source_revision':revision,'installed_at':'fixture'},sort_keys=True)+'\n')
for path in sorted(release.rglob('*'), key=lambda p: len(p.parts), reverse=True):
    os.chmod(path,0o555 if path.is_dir() else 0o444)
os.chmod(release,0o555); (runtime/'current').symlink_to(release)
PY_MAHO_MONITOR
mkdir -p "$XDG_CONFIG_HOME/systemd/user"
ln -s "$DATA_HOME/maho/runtime/current/systemd/user/maho-adaptive.service" "$XDG_CONFIG_HOME/systemd/user/maho-adaptive.service"
BEFORE_EXPECTED="$(count_kind persistence.expected-transition)"
BEFORE_UNEXPECTED="$(count_kind persistence.changed)"
bash "$MONITOR" cycle
[ "$(count_kind persistence.expected-transition)" -eq $((BEFORE_EXPECTED + 1)) ]
[ "$(count_kind persistence.changed)" -eq "$BEFORE_UNEXPECTED" ]
rm -f "$XDG_CONFIG_HOME/systemd/user/maho-adaptive.service"
chmod -R u+w "$DATA_HOME/maho/runtime/releases"
rm -rf "$DATA_HOME/maho/runtime"
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
grep -q 'runtime executable interval: 7s' <<< "$DOCTOR"
grep -q 'network listener interval: 10s' <<< "$DOCTOR"
echo "PASS"

echo "=== monotonic scheduler splits observer cadence without busy looping ==="
rm -rf "$STATE/guardian/providers"
MAHO_SECURITY_RUNTIME_INTERVAL=1 \
MAHO_SECURITY_NETWORK_INTERVAL=1 \
MAHO_SECURITY_PERSISTENCE_INTERVAL=20 \
MAHO_SECURITY_PRIVILEGE_INTERVAL=20 \
MAHO_SECURITY_PACKAGE_INTERVAL=30 \
MAHO_SECURITY_FINDINGS_INTERVAL=30 \
MAHO_SECURITY_INTEGRITY_CHECK_INTERVAL=30 \
MAHO_SECURITY_WATCH_ITERATIONS=3 \
bash "$MONITOR" watch
python - "$STATE/guardian/providers" <<'PY_SCHEDULER'
import json,sys
from pathlib import Path
root=Path(sys.argv[1])
sequence=lambda name: json.loads((root/f'{name}.json').read_text())['sequence']
assert sequence('security.runtime') == 3
assert sequence('security.network') == 3
assert sequence('security.persistence') == 1
assert sequence('security.privilege') == 1
assert sequence('security.packages') == 1
assert sequence('security.integrity') == 1
assert sequence('security.monitor') == 3
PY_SCHEDULER
echo "PASS"

echo "=== fast runtime scheduler observes an injected signal by the next bounded cycle ==="
rm -rf "$STATE/guardian/providers"
BEFORE="$(count_kind runtime.executable-observation)"
MAHO_SECURITY_RUNTIME_INTERVAL=1 \
MAHO_SECURITY_NETWORK_INTERVAL=20 \
MAHO_SECURITY_PERSISTENCE_INTERVAL=20 \
MAHO_SECURITY_PRIVILEGE_INTERVAL=20 \
MAHO_SECURITY_PACKAGE_INTERVAL=30 \
MAHO_SECURITY_FINDINGS_INTERVAL=30 \
MAHO_SECURITY_INTEGRITY_CHECK_INTERVAL=30 \
MAHO_SECURITY_WATCH_ITERATIONS=3 \
bash "$MONITOR" watch &
WATCH_PID=$!
for _ in $(seq 1 100); do
    [ -s "$STATE/guardian/providers/security.runtime.json" ] && break
    sleep 0.05
done
[ -s "$STATE/guardian/providers/security.runtime.json" ] || fail "runtime scheduler did not publish its initial heartbeat"
START_NS="$(date +%s%N)"
mkdir -p "$PROC/333"
ln -s "$FS/tmp/injected (deleted)" "$PROC/333/exe"
cat > "$PROC/333/status" <<EOF_STATUS
Name:\tinjected
State:\tS (sleeping)
Uid:\t$(id -u)\t$(id -u)\t$(id -u)\t$(id -u)
EOF_STATUS
printf 'injected\0' > "$PROC/333/cmdline"
DETECTED=0
for _ in $(seq 1 100); do
    if [ "$(count_kind runtime.executable-observation)" -gt "$BEFORE" ]; then
        DETECTED=1
        break
    fi
    sleep 0.05
done
END_NS="$(date +%s%N)"
rm -rf "$PROC/333"
wait "$WATCH_PID"
[ "$DETECTED" -eq 1 ] || fail "injected runtime signal was not observed"
LATENCY_MS=$(((END_NS - START_NS) / 1000000))
[ "$LATENCY_MS" -le 5000 ] || fail "runtime detection exceeded fixture bound: ${LATENCY_MS}ms"
echo "PASS observed runtime detection latency ${LATENCY_MS}ms (1s fixture interval, 5000ms startup bound)"

echo "ALL SECURITY MONITOR CONTRACTS PASS"
