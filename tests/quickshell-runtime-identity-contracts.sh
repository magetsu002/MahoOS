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
    mkdir -p "$runtime/bin" "$runtime/lib" "$runtime/config/quickshell/maho-clipboard"
    cp "$ROOT/bin/maho-clipboard" "$runtime/bin/maho-clipboard"
    cp "$ROOT/lib/runtime-instance.sh" "$runtime/lib/runtime-instance.sh"
    cp "$ROOT/config/quickshell/maho-clipboard/shell.qml" \
        "$runtime/config/quickshell/maho-clipboard/shell.qml"
}

RUNTIME_A="$TMP/runtime-a"
RUNTIME_B="$TMP/runtime-b"
make_runtime "$RUNTIME_A"
make_runtime "$RUNTIME_B"
export PATH="$FAKE_BIN:/usr/bin:/bin"
export XDG_RUNTIME_DIR="$TMP/run"
export FAKE_QUICKSHELL_LOG="$LOG"

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
    kill -0 "$PID_B" 2>/dev/null && pgrep -x quickshell >/dev/null 2>&1 && break
    sleep 0.025
done
bash "$RUNTIME_B/bin/maho-clipboard"
kill -0 "$PID_B" 2>/dev/null || fail "same-runtime toggle retired its owner"
grep -Fq "args=ipc --pid $PID_B call clipboard toggle" "$LOG" \
    || fail "same-runtime Clipboard invocation did not target its exact PID"
kill -TERM "$PID_B"
wait "$PID_B" 2>/dev/null || true

echo "PASS  stale Clipboard handoff and immutable Quickshell runtime identity"
