#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
PID=""
cleanup() {
    if [ -n "$PID" ]; then
        kill -CONT "$PID" 2>/dev/null || true
        kill "$PID" 2>/dev/null || true
        wait "$PID" 2>/dev/null || true
    fi
    rm -rf "$TMP"
}
trap cleanup EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
DB="$TMP/pacman-local"
FS="$TMP/fs"
mkdir -p "$HOME" "$XDG_STATE_HOME" "$DB/maho-test-sleeper-1.0-1" "$FS/usr/bin"
cp "$(command -v sleep)" "$FS/usr/bin/maho-test-sleeper"
chmod +x "$FS/usr/bin/maho-test-sleeper"

cat > "$DB/maho-test-sleeper-1.0-1/desc" <<'EOF_DESC'
%NAME%
maho-test-sleeper

%VERSION%
1.0-1

%FILES%
usr/bin/maho-test-sleeper

EOF_DESC

"$FS/usr/bin/maho-test-sleeper" 60 &
PID=$!
sleep 0.1
kill -0 "$PID"

ENGINE="$ROOT/lib/security_containment.py"
STATE="$XDG_STATE_HOME/maho/security"

echo "=== explicit freeze contains matching user process ==="
RESULT="$(python "$ENGINE" freeze maho-test-sleeper \
    --version 1.0-1 \
    --finding-id test-containment-001 \
    --db-root "$DB" \
    --proc-root /proc \
    --fs-root "$FS" \
    --state-root "$STATE" \
    --uid "$(id -u)")"
printf '%s\n' "$RESULT" | python - "$PID" <<'PY'
import json,sys
pid=int(sys.argv[1]); r=json.load(sys.stdin)
assert r["result"] == "contained", r
assert [p["pid"] for p in r["contained"]] == [pid]
assert r["session_id"].startswith("contain-")
PY
STAT="$(ps -o stat= -p "$PID" | tr -d ' ')"
[[ "$STAT" == T* ]] || { echo "FAIL: process was not stopped: $STAT" >&2; exit 1; }
SESSION="$(printf '%s\n' "$RESULT" | python -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')"
SESSION_PATH="$STATE/containment/$SESSION.json"
[ -f "$SESSION_PATH" ]
[ "$(stat -c '%a' "$STATE/containment")" = 700 ]
[ "$(stat -c '%a' "$SESSION_PATH")" = 600 ]
echo "PASS"

echo "=== release verifies pid identity and resumes process ==="
RESULT="$(python "$ENGINE" release "$SESSION" --proc-root /proc --state-root "$STATE")"
printf '%s\n' "$RESULT" | python - "$PID" <<'PY'
import json,sys
pid=int(sys.argv[1]); r=json.load(sys.stdin)
assert r["result"] == "released", r
assert [p["pid"] for p in r["released"]] == [pid]
PY
sleep 0.05
STAT="$(ps -o stat= -p "$PID" | tr -d ' ')"
[[ "$STAT" != T* ]] || { echo "FAIL: process remained stopped: $STAT" >&2; exit 1; }
kill -0 "$PID"
echo "PASS"

echo "=== version mismatch fails closed without signaling process ==="
RESULT="$(python "$ENGINE" freeze maho-test-sleeper \
    --version 9.9-9 \
    --finding-id test-containment-002 \
    --db-root "$DB" \
    --proc-root /proc \
    --fs-root "$FS" \
    --state-root "$STATE" \
    --uid "$(id -u)")"
printf '%s\n' "$RESULT" | python -c 'import json,sys; assert json.load(sys.stdin)["result"] == "version-mismatch"'
STAT="$(ps -o stat= -p "$PID" | tr -d ' ')"
[[ "$STAT" != T* ]] || { echo "FAIL: mismatched version was contained" >&2; exit 1; }
echo "PASS"

echo "ALL SECURITY CONTAINMENT CONTRACTS PASS"
