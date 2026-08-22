#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_TEST_ADAPTER_STATE="$TMP/adapter-state.json"
export MAHO_ADAPTER_REGISTRY="$TMP/adapters.json"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME"
printf '%s\n' '{"operation":"test-op","value":"old"}' > "$MAHO_TEST_ADAPTER_STATE"

cat > "$MAHO_ADAPTER_REGISTRY" <<'JSON'
{
  "version": 1,
  "operations": {
    "test-op": {
      "adapter": "tests/fixtures/fake-adapter.sh",
      "domain": "test",
      "resource": "test.resource"
    }
  }
}
JSON

source "$ROOT/lib/authority.sh"
source "$ROOT/lib/decision.sh"
source "$ROOT/lib/events.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }
execute() { bash "$ROOT/bin/maho-adapt" execute "$1"; }

echo "=== registry ==="
bash "$ROOT/bin/maho-adapt" validate-registry | grep -q '^PASS$'
bash "$ROOT/bin/maho-adapt" list | grep -q 'test-op'
echo "PASS"

echo "=== execution-time ownership fails closed ==="
DECISION="$(maho_decision_create test example adapt test.resource 'test mutation' '{}' '{"operation":"test-op","value":"new"}')"
RESULT="$(execute "$DECISION")"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "skipped"
assert r["action"] == "adapt"
assert "owner=user" in r["reason"]
'
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json,sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "old"
PY
LAST="$(maho_event_last test)"
printf '%s\n' "$LAST" | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "authorization.denied"
assert e["status"] == "skipped"
'
echo "PASS"

echo "=== authorized decision uses one correlated wheel cycle ==="
maho_owner_set test.resource maho >/dev/null
RESULT="$(execute "$DECISION")"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "verified"
assert r["cycle_id"].startswith("cyc-test-")
assert r["desired"]["value"] == "new"
'
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json,sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "new"
PY
CYCLE="$(printf '%s\n' "$RESULT" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
assert [r["kind"] for r in rows] == [
    "policy.decision",
    "authorization.allowed",
    "adapter.capture",
    "adapter.apply",
    "adapter.verify",
    "adaptation.completed",
]
assert len({r["cycle_id"] for r in rows}) == 1
'
echo "PASS"

echo "=== already-verified desired state does not mutate ==="
BEFORE_HASH="$(sha256sum "$MAHO_TEST_ADAPTER_STATE" | cut -d' ' -f1)"
RESULT="$(execute "$DECISION")"
AFTER_HASH="$(sha256sum "$MAHO_TEST_ADAPTER_STATE" | cut -d' ' -f1)"
[ "$BEFORE_HASH" = "$AFTER_HASH" ] || fail "already-satisfied execution rewrote adapter state"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "verified"
assert r["action"] == "adapt"
assert "already verified" in r["reason"]
'
CYCLE="$(printf '%s\n' "$RESULT" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
assert [r["kind"] for r in rows] == [
    "policy.decision",
    "authorization.allowed",
    "adaptation.satisfied",
]
'
echo "PASS"

echo "=== do-nothing never invokes adapter ==="
printf '%s\n' '{"operation":"test-op","value":"stable"}' > "$MAHO_TEST_ADAPTER_STATE"
DECISION_NOOP="$(maho_decision_create test noop do-nothing test.resource 'nothing useful to do' '{}' '{}')"
RESULT="$(execute "$DECISION_NOOP")"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "skipped"
assert r["action"] == "do-nothing"
'
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json,sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "stable"
PY
echo "PASS"

echo "=== propose never invokes adapter ==="
DECISION_PROPOSE="$(maho_decision_create test review propose test.resource 'needs review' '{}' '{"operation":"test-op","value":"danger"}')"
RESULT="$(execute "$DECISION_PROPOSE")"
printf '%s\n' "$RESULT" | python -c '
import json,sys
r=json.load(sys.stdin)
assert r["status"] == "proposed"
assert r["action"] == "propose"
'
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json,sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "stable"
PY
echo "PASS"

echo "=== registry/resource mismatch fails closed ==="
BAD="$(maho_decision_create test example adapt other.resource 'wrong target' '{}' '{"operation":"test-op","value":"bad"}')"
maho_owner_set other.resource maho >/dev/null
if execute "$BAD" >/dev/null 2>&1; then
    fail "registry/resource mismatch was accepted"
fi
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json,sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "stable"
PY
echo "PASS"

echo "=== readable non-executable shell adapter is supported ==="
DECISION_SHELL="$(maho_decision_create test example adapt test.resource 'shell adapter' '{}' '{"operation":"test-op","value":"shell-ok"}')"
RESULT="$(execute "$DECISION_SHELL")"
printf '%s\n' "$RESULT" | python -c 'import json,sys; assert json.load(sys.stdin)["status"] == "verified"'
echo "PASS"

echo "ALL ADAPT EXECUTOR CONTRACTS PASS"
