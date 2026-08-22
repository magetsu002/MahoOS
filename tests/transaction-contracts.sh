#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export MAHO_ROOT="$ROOT"
export MAHO_TEST_ADAPTER_STATE="$TMP/adapter-state.json"

mkdir -p "$HOME" "$XDG_STATE_HOME"
printf '%s\n' '{"value":"old"}' > "$MAHO_TEST_ADAPTER_STATE"

# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"
# shellcheck source=../lib/cycle.sh
source "$ROOT/lib/cycle.sh"
# shellcheck source=../lib/transaction.sh
source "$ROOT/lib/transaction.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

ADAPTER="$TMP/fake-adapter"
cat > "$ADAPTER" <<'ADAPTER_SCRIPT'
#!/usr/bin/env bash
set -euo pipefail

cmd="$1"
payload="$2"

case "$cmd" in
    capture)
        cat "$MAHO_TEST_ADAPTER_STATE"
        ;;
    apply)
        python - "$payload" "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json, sys
from pathlib import Path
value = json.loads(sys.argv[1])
Path(sys.argv[2]).write_text(json.dumps(value, sort_keys=True) + "\n")
PY
        ;;
    verify)
        [ "${MAHO_TEST_VERIFY_FAIL:-0}" != "1" ] || exit 1
        python - "$payload" "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json, sys
from pathlib import Path
expected = json.loads(sys.argv[1])
actual = json.loads(Path(sys.argv[2]).read_text())
raise SystemExit(0 if actual == expected else 1)
PY
        ;;
    rollback)
        python - "$payload" "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json, sys
from pathlib import Path
before = json.loads(sys.argv[1])
Path(sys.argv[2]).write_text(json.dumps(before, sort_keys=True) + "\n")
PY
        ;;
    *)
        exit 2
        ;;
esac
ADAPTER_SCRIPT
chmod +x "$ADAPTER"

echo "=== verified transaction ==="
RESULT="$(maho_transaction_execute "$ADAPTER" '{"value":"new"}' test test.resource)"
printf '%s\n' "$RESULT" | python -c '
import json, sys
r = json.load(sys.stdin)
assert r["status"] == "verified"
assert r["desired"]["value"] == "new"
assert r["before"]["value"] == "old"
assert r["cycle_id"].startswith("cyc-test-")
'
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json, sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "new"
PY
CYCLE="$(printf '%s\n' "$RESULT" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin if line.strip()]
assert [r["kind"] for r in rows] == ["adapter.capture", "adapter.apply", "adapter.verify"]
assert rows[-1]["status"] == "verified"
'
echo "PASS"

echo "=== verification failure rolls back ==="
printf '%s\n' '{"value":"stable"}' > "$MAHO_TEST_ADAPTER_STATE"
export MAHO_TEST_VERIFY_FAIL=1
if maho_transaction_execute "$ADAPTER" '{"value":"bad"}' test test.resource >/dev/null 2>&1; then
    fail "transaction unexpectedly succeeded despite verify failure"
fi
unset MAHO_TEST_VERIFY_FAIL
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json, sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["value"] == "stable"
PY
LAST="$(maho_event_last test)"
CYCLE="$(printf '%s\n' "$LAST" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin if line.strip()]
assert rows[-2]["kind"] == "adapter.verify"
assert rows[-2]["status"] == "failed"
assert rows[-1]["kind"] == "adapter.rollback"
assert rows[-1]["status"] == "rolled_back"
'
echo "PASS"

echo "=== unsafe adapter reference rejected ==="
if maho_transaction_execute relative-adapter '{}' test test.resource >/dev/null 2>&1; then
    fail "relative adapter path was accepted"
fi
echo "PASS"

echo "ALL TRANSACTION CONTRACTS PASS"
