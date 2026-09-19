#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/bin/maho-memory-certify"
CERT="$ROOT/lib/maho_memory_certify.py"
APP_MODEL="$ROOT/lib/maho_app_model.py"
SETUP="$ROOT/bin/maho-setup"
[ -x "$BIN" ] && [ -r "$CERT" ] || { echo "FAIL: memory certifier entrypoint is incomplete" >&2; exit 1; }
bash -n "$BIN"
python3 -m py_compile "$CERT"
require() { grep -Fq -- "$1" "$CERT" || { echo "FAIL: missing memory-certification invariant: $1" >&2; exit 1; }; }
require '"4g": {"memory_max": 4 * GIB'
require '"8g": {"memory_max": 8 * GIB'
require '"Hyprland", "--config"'
require 'config/quickshell/maho-shell/shell.qml'
require 'config/quickshell/maho-shell/dock-shell.qml'
require 'config/quickshell/maho-notify/shell.qml'
require 'maho-guardian-watch'
require 'bin/maho-adaptive'
require 'xdg-desktop-portal-hyprland'
require 'MemoryMax='
require 'MemoryHigh='
require 'pressure_worker_code()'
require 'memory.events'
require 'memory.pressure'
require 'memory.swap.current'
require 'SwapPss:'
require 'animated_wallpaper'
require 'no playback generated'
grep -Fq -- '"--property=Slice=app.slice"' "$APP_MODEL" || { echo "FAIL: real app helper no longer targets app.slice" >&2; exit 1; }
grep -Fq -- 'systemd-run' "$CERT" || { echo "FAIL: app launch interception is missing" >&2; exit 1; }
if grep -Fq 'offscreen' "$CERT"; then echo "FAIL: offscreen Qt backend is not representative" >&2; exit 1; fi
if grep -Fq -- '--execute-certified' "$CERT"; then echo "FAIL: nested Adaptive must remain non-mutating" >&2; exit 1; fi
if grep -Eq 'systemctl.*(--user[[:space:]]+)?(stop|restart).*maho-(shell|dock|notify)' "$CERT"; then echo "FAIL: certifier must not restart physical Maho surfaces" >&2; exit 1; fi
grep -Eq 'maho-memory-certify' "$SETUP" || { echo "FAIL: setup does not install memory certifier" >&2; exit 1; }
"$BIN" --help >/dev/null
"$BIN" run --help >/dev/null
echo 'ALL MEMORY CERTIFICATION CONTRACTS PASS'
