#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
GUARD="$ROOT/bin/maho-vesktop-guard"
PATCHER="$ROOT/lib/maho_vesktop_patch.py"

bash -n "$GUARD"
python3 -m py_compile "$PATCHER"

python3 - "$PATCHER" "$GUARD" <<'PY'
import importlib.util
from pathlib import Path
import sys

patcher_path = Path(sys.argv[1])
guard_path = Path(sys.argv[2])

spec = importlib.util.spec_from_file_location("maho_vesktop_patch", patcher_path)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

source = (
    "prefix;"
    + module.SECOND_INSTANCE_OLD
    + ";middle;"
    + module.OWNER_ANCHOR
    + "fallback;tail"
)
patched = module.patch_main(source)

assert module.SECOND_INSTANCE_OLD not in patched
assert module.OWNER_ANCHOR not in patched
assert "__mahoVesktopActivate" in patched
assert "__mahoVesktopSetupControl" in patched
assert 'q.action==="activate"' in patched
assert 'q.action==="close"' in patched
assert 'q.action==="hide"' in patched
assert 'q.action==="minimize"' in patched
assert 'q.action==="state"' in patched
assert "chmodSync(s,384)" in patched
assert "MAHO_VESKTOP_OWNER_FILE" in patched
assert "unlinkSync(o)" in patched

try:
    module.patch_main("unexpected Vesktop runtime shape")
except RuntimeError:
    pass
else:
    raise AssertionError("patch mismatch did not fail closed")

guard = guard_path.read_text()
assert 'LOCK="$RUNTIME_DIR/maho-vesktop-profile.lock"' in guard
assert 'SOCKET="$RUNTIME_DIR/maho-vesktop-control.sock"' in guard
assert "profile owner exists but could not be activated" in guard
assert "unmanaged Vesktop profile owner is already running" in guard
assert '--type=*|*" --type="*) has_type=1 ;;' in guard
assert 'first_exec="${first%% *}"' in guard
assert 'case "${first_exec##*/}" in' in guard
launch_tail = guard.split('local start_ticks', 1)[1]
launch_tail = launch_tail.split('indexeddb_lock_holders()', 1)[0]
exec_tail = launch_tail.split('log_event "action=launch route=canonical', 1)[1]
assert "flock -u 9" not in exec_tail
assert 'VESKTOP_HOME="${MAHO_VESKTOP_HOME:-/opt/vesktop}"' in guard
assert 'SOURCE_ASAR="${MAHO_VESKTOP_SOURCE_ASAR:-$VESKTOP_HOME/resources/app.asar}"' in guard
assert 'ELECTRON_BIN="${MAHO_VESKTOP_ELECTRON:-/usr/bin/electron43}"' in guard
assert 'export MAHO_VESKTOP_OWNER_FILE="$OWNER"' in guard
assert 'recorded_owner_is_current()' in guard
assert 'patcher_sha256()' in guard
assert 'grep -Fxq "patcher_sha256=$expected_patcher" "$MANIFEST"' in guard
assert 'grep -Fxq "runtime_sha256=$expected_runtime" "$MANIFEST"' in guard
assert 'recover_recorded_ghost()' in guard
assert 'kill -TERM "$pid"' in guard
assert 'flock -w 2 9' in guard
assert 'cd "$VESKTOP_HOME" || return 1' in launch_tail
assert 'exec "$ELECTRON_BIN"' in launch_tail
assert 'exec /opt/vesktop/vesktop' not in launch_tail
assert '/usr/lib/vesktop' not in guard
PY

TMP="$(mktemp -d)"
GHOST=""
cleanup() {
    if [ -n "$GHOST" ] && kill -0 "$GHOST" 2>/dev/null; then
        kill -TERM "$GHOST" 2>/dev/null || true
        wait "$GHOST" 2>/dev/null || true
    fi
    rm -rf "$TMP"
}
trap cleanup EXIT

export HOME="$TMP/home"
export XDG_RUNTIME_DIR="$TMP/runtime"
export XDG_STATE_HOME="$TMP/state"
export XDG_DATA_HOME="$TMP/data"
export MAHO_VESKTOP_HOME="$TMP/opt/vesktop"
export MAHO_VESKTOP_ELECTRON="$TMP/bin/fake-electron"
export MAHO_VESKTOP_TEST_MARKER="$TMP/electron-args"
mkdir -p "$HOME/.config/vesktop/sessionData" "$XDG_RUNTIME_DIR" "$XDG_STATE_HOME" \
    "$XDG_DATA_HOME/maho/vesktop-runtime" "$MAHO_VESKTOP_HOME/resources" "$TMP/bin"

printf 'source-runtime\n' >"$MAHO_VESKTOP_HOME/resources/app.asar"
printf 'patched-runtime\n' >"$XDG_DATA_HOME/maho/vesktop-runtime/app.asar"
SOURCE_SHA="$(sha256sum "$MAHO_VESKTOP_HOME/resources/app.asar" | awk '{print $1}')"
PATCHER_SHA="$(sha256sum "$PATCHER" | awk '{print $1}')"
PATCHED_SHA="$(sha256sum "$XDG_DATA_HOME/maho/vesktop-runtime/app.asar" | awk '{print $1}')"
cat >"$XDG_DATA_HOME/maho/vesktop-runtime/manifest" <<EOF
source=$MAHO_VESKTOP_HOME/resources/app.asar
source_sha256=$SOURCE_SHA
patcher_sha256=$PATCHER_SHA
runtime_sha256=$PATCHED_SHA
package=vesktop-bin test
generated=test
EOF

cat >"$TMP/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat >"$TMP/bin/hyprctl" <<'EOF'
#!/usr/bin/env bash
if [ "${1:-}" = clients ] && [ "${2:-}" = -j ]; then
    printf '[]\n'
    exit 0
fi
exit 1
EOF
cat >"$MAHO_VESKTOP_ELECTRON" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$MAHO_VESKTOP_TEST_MARKER"
rm -f "$MAHO_VESKTOP_OWNER_FILE" "$MAHO_VESKTOP_CONTROL_SOCKET"
EOF
chmod +x "$TMP/bin/systemctl" "$TMP/bin/hyprctl" "$MAHO_VESKTOP_ELECTRON"
export PATH="$TMP/bin:$PATH"

LOCK="$XDG_RUNTIME_DIR/maho-vesktop-profile.lock"
PATCHED="$XDG_DATA_HOME/maho/vesktop-runtime/app.asar"
cat >"$TMP/ghost.py" <<'PY_GHOST'
import fcntl
import signal
import sys

lock_path, runtime_path = sys.argv[1:3]
lock = open(lock_path, "w")
fcntl.flock(lock, fcntl.LOCK_EX)

def terminate(_signum, _frame):
    raise SystemExit(0)

signal.signal(signal.SIGTERM, terminate)
while True:
    signal.pause()
PY_GHOST
bash -c 'exec -a vesktop python3 "$1" "$2" "$3"' _ "$TMP/ghost.py" "$LOCK" "$PATCHED" &
GHOST="$!"

for _ in $(seq 1 50); do
    if ! flock -n "$LOCK" true 2>/dev/null; then
        break
    fi
    read -r -t 0.02 _ || true
done
if flock -n "$LOCK" true 2>/dev/null; then
    echo "FAIL ghost fixture did not acquire profile lock" >&2
    exit 1
fi

START_TICKS="$(awk '{print $22}' "/proc/$GHOST/stat")"
cat >"$XDG_RUNTIME_DIR/maho-vesktop-owner" <<EOF
pid=$GHOST
start_ticks=$START_TICKS
runtime=$PATCHED
profile=$HOME/.config/vesktop/sessionData
EOF

"$GUARD"

if kill -0 "$GHOST" 2>/dev/null; then
    echo "FAIL managed ghost owner survived recovery" >&2
    exit 1
fi
wait "$GHOST" 2>/dev/null || true
GHOST=""

grep -Fxq "$PATCHED" "$MAHO_VESKTOP_TEST_MARKER"
grep -Fq "action=recover-ghost result=pass" "$XDG_STATE_HOME/maho/vesktop-launch.log"
grep -Fq "action=launch route=canonical started_new=yes" "$XDG_STATE_HOME/maho/vesktop-launch.log"
[ ! -e "$XDG_RUNTIME_DIR/maho-vesktop-owner" ] || {
    echo "FAIL stale owner metadata survived fake Electron exit" >&2
    exit 1
}
echo "PASS managed unactivatable ghost is recovered before relaunch"

git -C "$ROOT" diff --check

echo "PASS vesktop session reliability contracts"
