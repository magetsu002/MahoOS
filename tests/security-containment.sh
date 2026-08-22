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
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_PACMAN_DB_ROOT="$TMP/pacman-local"
export MAHO_FS_ROOT="$TMP/fs"
export MAHO_PROC_ROOT=/proc
DB="$MAHO_PACMAN_DB_ROOT"
FS="$MAHO_FS_ROOT"
mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME" "$DB/maho-test-sleeper-1.0-1" "$FS/usr/bin"
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
python - "$PID" "$RESULT" <<'PY'
import json,sys
pid=int(sys.argv[1]); r=json.loads(sys.argv[2])
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
python - "$PID" "$RESULT" <<'PY'
import json,sys
pid=int(sys.argv[1]); r=json.loads(sys.argv[2])
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

echo "=== CLI containment requires explicit confirmation and preserves evidence first ==="
FINDING="$TMP/confirmed.json"
cat > "$FINDING" <<'EOF_FINDING'
{
  "version": 1,
  "id": "test-containment-cli-001",
  "source": "test-feed",
  "type": "package-version",
  "severity": "critical",
  "confidence": "confirmed",
  "summary": "Test package is confirmed affected.",
  "package": {"name": "maho-test-sleeper", "versions": ["1.0-1"]}
}
EOF_FINDING

if bash "$ROOT/bin/maho-contain" freeze "$FINDING" >/dev/null 2>&1; then
    echo "FAIL: containment proceeded without --confirm" >&2
    exit 1
fi
STAT="$(ps -o stat= -p "$PID" | tr -d ' ')"
[[ "$STAT" != T* ]] || { echo "FAIL: process changed state without confirmation" >&2; exit 1; }

OUTPUT="$(bash "$ROOT/bin/maho-contain" freeze "$FINDING" --confirm)"
SESSION="$(printf '%s\n' "$OUTPUT" | awk '/^Session:/ {print $2}')"
[ -n "$SESSION" ] || { echo "FAIL: CLI containment did not return session" >&2; exit 1; }
STAT="$(ps -o stat= -p "$PID" | tr -d ' ')"
[[ "$STAT" == T* ]] || { echo "FAIL: CLI containment did not stop target" >&2; exit 1; }

[ "$(find "$STATE/findings" -maxdepth 1 -type f -name '*.json' | wc -l)" -ge 1 ]
[ "$(find "$STATE/provenance/snapshots" -maxdepth 1 -type f -name '*.json' | wc -l)" -ge 1 ]
[ "$(find "$STATE/persistence/snapshots" -maxdepth 1 -type f -name '*.json' | wc -l)" -ge 1 ]
[ ! -e "$STATE/provenance/baseline.json" ]
[ ! -e "$STATE/persistence/baseline.json" ]
python - "$XDG_STATE_HOME/maho/history/events.jsonl" <<'PY'
import json,sys
from pathlib import Path
rows=[]
for line in Path(sys.argv[1]).read_text().splitlines():
    try: rows.append(json.loads(line))
    except Exception: pass
assert any(r.get("kind") == "containment.evidence-preserved" for r in rows)
assert any(r.get("kind") == "containment.process-freeze" and r.get("status") == "contained" for r in rows)
PY

bash "$ROOT/bin/maho-contain" release "$SESSION" >/dev/null
sleep 0.05
STAT="$(ps -o stat= -p "$PID" | tr -d ' ')"
[[ "$STAT" != T* ]] || { echo "FAIL: CLI release did not resume target" >&2; exit 1; }
echo "PASS"

echo "ALL SECURITY CONTAINMENT CONTRACTS PASS"
