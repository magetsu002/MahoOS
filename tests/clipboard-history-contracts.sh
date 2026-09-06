#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER="$ROOT/bin/maho-clipboard-history"
SERVICE="$ROOT/systemd/user/maho-clipboard-history.service"
FRONTEND=(
    "$ROOT/bin/maho-clipboard"
    "$ROOT/config/quickshell/maho-clipboard/clipboard.py"
    "$ROOT/config/quickshell/maho-clipboard/ClipboardPanel.qml"
    "$ROOT/config/quickshell/maho-clipboard/ClipboardState.qml"
    "$ROOT/config/quickshell/maho-clipboard/shell.qml"
)

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}

[ -x "$OWNER" ] || fail "history owner is missing or not executable"
[ -r "$SERVICE" ] || fail "history user service is missing"
bash -n "$OWNER"

require_text "$OWNER" 'flock -n 9' 'history owner has no singleton lock'
require_text "$OWNER" 'wl-paste --type text --watch cliphist store' 'text clipboard capture missing'
require_text "$OWNER" 'wl-paste --type image --watch cliphist store' 'image clipboard capture missing'
require_text "$SERVICE" 'ExecStart=%h/.local/bin/maho-clipboard-history serve' 'service does not invoke the dedicated owner'
require_text "$SERVICE" 'Restart=always' 'history owner is not automatically recovered'

for file in "${FRONTEND[@]}"; do
    if grep -Eq 'wl-paste[[:space:]].*--watch|cliphist[[:space:]]+store' "$file"; then
        fail "frontend still owns clipboard capture: ${file#$ROOT/}"
    fi
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/runtime"
LOG="$TMP/watchers.log"

cat > "$TMP/bin/wl-paste" <<'EOF_WLPASTE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${MAHO_TEST_LOG:?}"
trap 'exit 0' TERM INT
while :; do sleep 0.1; done
EOF_WLPASTE
chmod +x "$TMP/bin/wl-paste"

cat > "$TMP/bin/cliphist" <<'EOF_CLIPHIST'
#!/usr/bin/env bash
exit 0
EOF_CLIPHIST
chmod +x "$TMP/bin/cliphist"

PATH="$TMP/bin:$PATH" \
XDG_RUNTIME_DIR="$TMP/runtime" \
MAHO_TEST_LOG="$LOG" \
    "$OWNER" serve &
OWNER_PID=$!

for _ in $(seq 1 50); do
    [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -ge 2 ] && break
    sleep 0.05
done

[ -f "$LOG" ] || fail "history owner never started capture workers"
[ "$(grep -Fc -- '--type text --watch cliphist store' "$LOG")" -eq 1 ] || fail "text watcher count is not exactly one"
[ "$(grep -Fc -- '--type image --watch cliphist store' "$LOG")" -eq 1 ] || fail "image watcher count is not exactly one"

PATH="$TMP/bin:$PATH" \
XDG_RUNTIME_DIR="$TMP/runtime" \
MAHO_TEST_LOG="$LOG" \
    "$OWNER" serve >/dev/null 2>&1

sleep 0.1
[ "$(grep -Fc -- '--type text --watch cliphist store' "$LOG")" -eq 1 ] || fail "second owner duplicated text watcher"
[ "$(grep -Fc -- '--type image --watch cliphist store' "$LOG")" -eq 1 ] || fail "second owner duplicated image watcher"

kill "$OWNER_PID"

set +e
wait "$OWNER_PID"
OWNER_STATUS=$?
set -e

[ "$OWNER_STATUS" -eq 0 ] ||
    fail "intentional history-owner shutdown exited $OWNER_STATUS instead of 0"

printf 'PASS  persistent clipboard history owner is singleton, UI-independent, and stops cleanly\n'
