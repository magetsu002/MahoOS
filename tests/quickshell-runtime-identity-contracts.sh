#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'jobs -p | xargs -r kill 2>/dev/null || true; rm -rf -- "$TMP"' EXIT
FAKE_BIN="$TMP/bin"
LOG="$TMP/quickshell.log"
mkdir -p "$FAKE_BIN" "$TMP/run"

fail() { echo "FAIL: $*" >&2; exit 1; }

cat >"$FAKE_BIN/quickshell" <<'PY'
#!/usr/bin/env python3
import ctypes
import os
from pathlib import Path
import signal
import sys
import time

log = Path(os.environ["FAKE_QUICKSHELL_LOG"])
args = sys.argv[1:]
identity = os.environ.get("MAHO_RUNTIME_IDENTITY", "missing")
with log.open("a", encoding="utf-8") as handle:
    handle.write(f"identity={identity} args={' '.join(args)}\n")

if args and args[0] == "ipc":
    pid = int(args[args.index("--pid") + 1])
    method = args[-2] if args[-1].startswith("/") else args[-1]
    if method in ("retire", "close"):
        os.kill(pid, signal.SIGTERM)
    raise SystemExit(0)

if os.environ.get("FAKE_QUICKSHELL_HOLD") == "1":
    ctypes.CDLL(None).prctl(15, b"quickshell", 0, 0, 0)
    while True:
        time.sleep(1)
PY
chmod +x "$FAKE_BIN/quickshell"
ln -s /usr/bin/true "$FAKE_BIN/cliphist"
ln -s /usr/bin/true "$FAKE_BIN/wl-copy"

make_runtime() {
    local runtime="$1"
    mkdir -p "$runtime/bin" "$runtime/lib" \
        "$runtime/config/quickshell/maho-clipboard" \
        "$runtime/config/quickshell/maho-link" \
        "$runtime/config/quickshell/maho-launcher"
    cp "$ROOT/bin/maho-clipboard" "$ROOT/bin/maho-link" "$ROOT/bin/maho-launcher" "$runtime/bin/"
    cp "$ROOT/lib/runtime-instance.sh" "$runtime/lib/runtime-instance.sh"
    cp "$ROOT/lib/maho_launcher_backend.py" "$runtime/lib/maho_launcher_backend.py"
    cp "$ROOT/config/quickshell/maho-clipboard/shell.qml" \
        "$runtime/config/quickshell/maho-clipboard/shell.qml"
    cp "$ROOT/config/quickshell/maho-link/shell.qml" \
        "$runtime/config/quickshell/maho-link/shell.qml"
    cp "$ROOT/config/quickshell/maho-launcher/shell.qml" \
        "$ROOT/config/quickshell/maho-launcher/LauncherBackdrop.qml" \
        "$runtime/config/quickshell/maho-launcher/"
}

RUNTIME_A="$TMP/runtime-a"
RUNTIME_B="$TMP/runtime-b"
make_runtime "$RUNTIME_A"
make_runtime "$RUNTIME_B"
export PATH="$FAKE_BIN:/usr/bin:/bin"
export XDG_RUNTIME_DIR="$TMP/run"
export FAKE_QUICKSHELL_LOG="$LOG"
unset MAHO_ROOT || true
source "$ROOT/lib/runtime-instance.sh"

FAKE_QUICKSHELL_HOLD=1 bash "$RUNTIME_A/bin/maho-clipboard" &
PID_A=$!
for _ in $(seq 1 40); do
    grep -Fq "identity=$RUNTIME_A args=-p" "$LOG" 2>/dev/null && break
    sleep 0.025
done
kill -0 "$PID_A" 2>/dev/null || fail "runtime A fixture did not stay alive"

bash "$RUNTIME_B/bin/maho-clipboard"
if kill -0 "$PID_A" 2>/dev/null; then
    fail "runtime A survived the explicit runtime B handoff"
fi
grep -Fq "args=ipc --pid $PID_A call clipboard retire $RUNTIME_B" "$LOG" \
    || fail "runtime B did not retire the exact stale Clipboard PID"
grep -Fq "identity=$RUNTIME_B args=-p" "$LOG" \
    || fail "runtime B did not become the selected Clipboard process"

FAKE_QUICKSHELL_HOLD=1 bash "$RUNTIME_B/bin/maho-clipboard" &
PID_B=$!
for _ in $(seq 1 40); do
    [ "$(ps -o comm= -p "$PID_B" 2>/dev/null | tr -d ' ')" = "quickshell" ] && break
    sleep 0.025
done
[ "$(ps -o comm= -p "$PID_B" 2>/dev/null | tr -d ' ')" = "quickshell" ] \
    || fail "same-runtime Clipboard fixture was not ready"
bash "$RUNTIME_B/bin/maho-clipboard"
kill -0 "$PID_B" 2>/dev/null || fail "same-runtime toggle retired its owner"
grep -Fq "args=ipc --pid $PID_B call clipboard toggle" "$LOG" \
    || fail "same-runtime Clipboard invocation did not target its exact PID"
kill -TERM "$PID_B"
wait "$PID_B" 2>/dev/null || true

FAKE_QUICKSHELL_HOLD=1 bash "$RUNTIME_A/bin/maho-link" wifi &
PID_LINK_A=$!
for _ in $(seq 1 40); do
    grep -Fq "identity=$RUNTIME_A args=-p $RUNTIME_A/config/quickshell/maho-link/shell.qml" "$LOG" 2>/dev/null && break
    sleep 0.025
done
bash "$RUNTIME_B/bin/maho-link" bluetooth
kill -0 "$PID_LINK_A" 2>/dev/null && fail "runtime A Maho Link survived handoff"
grep -Fq "args=ipc --pid $PID_LINK_A call link retire $RUNTIME_B" "$LOG" \
    || fail "Maho Link did not retire the exact stale PID"

mkdir -p "$TMP/home" "$TMP/cache"
export HOME="$TMP/home"
export XDG_CACHE_HOME="$TMP/cache"
unset HYPRLAND_INSTANCE_SIGNATURE || true
FAKE_QUICKSHELL_HOLD=1 bash "$RUNTIME_A/bin/maho-launcher" run \
    >"$TMP/launcher-a.out" 2>&1 &
PID_LAUNCHER_A=$!
for _ in $(seq 1 40); do
    grep -Fq "identity=$RUNTIME_A args=-p $RUNTIME_A/config/quickshell/maho-launcher/shell.qml" "$LOG" 2>/dev/null && break
    sleep 0.025
done
PID_LAUNCHER_QS=""
while read -r candidate; do
    if [ "$(maho_process_runtime_identity "$candidate" 2>/dev/null || true)" = "$RUNTIME_A" ]; then
        PID_LAUNCHER_QS="$candidate"
        break
    fi
done < <(maho_quickshell_config_pids "/quickshell/maho-launcher/shell.qml")
[ -n "$PID_LAUNCHER_QS" ] || fail "runtime A Launcher Quickshell PID was not identified"
bash "$RUNTIME_B/bin/maho-launcher" run
kill -0 "$PID_LAUNCHER_A" 2>/dev/null && fail "runtime A Launcher survived handoff"
grep -Fq "args=ipc --pid $PID_LAUNCHER_QS call launcher close" "$LOG" \
    || fail "Launcher did not close the exact stale PID"

for launcher in maho-clipboard maho-link maho-launcher; do
    grep -Fq 'MAHO_RUNTIME_IDENTITY' "$ROOT/bin/$launcher" \
        || fail "$launcher does not publish immutable runtime identity"
    grep -Fq 'maho_process_runtime_identity' "$ROOT/bin/$launcher" \
        || fail "$launcher does not compare process identity before reuse"
done

echo "PASS  stale Clipboard, Link, and Launcher handoff by immutable runtime identity"
