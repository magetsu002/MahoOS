#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export MAHO_ROOT="$ROOT"

mkdir -p "$HOME" "$XDG_STATE_HOME"

# shellcheck source=../lib/cycle.sh
source "$ROOT/lib/cycle.sh"
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

echo "=== cycle identity ==="
CYCLE="$(maho_cycle_new appearance)"
maho_cycle_valid "$CYCLE" || fail "generated cycle id is invalid"
if maho_cycle_valid 'not-a-cycle'; then
    fail "invalid cycle id accepted"
fi
echo "PASS"

echo "=== correlated events ==="
MAHO_CYCLE_ID="$CYCLE" maho_event_emit \
    appearance wallpaper.changed observed info \
    'Wallpaper changed' '' test-provider '{"step":1}' >/dev/null

MAHO_CYCLE_ID="$CYCLE" maho_event_emit \
    appearance policy.decision proposed info \
    'Policy requested adaptation' appearance.hyprland.borders maho-policy '{"step":2}' >/dev/null

MAHO_CYCLE_ID="$CYCLE" maho_event_emit \
    appearance theme.applied verified low \
    'Theme adaptation verified' appearance.hyprland.borders hyprland '{"step":3}' >/dev/null

COUNT="$(maho_event_cycle "$CYCLE" | wc -l | tr -d ' ')"
[ "$COUNT" = 3 ] || fail "expected 3 correlated events, got $COUNT"

maho_event_cycle "$CYCLE" | python -c '
import json, sys
rows = [json.loads(line) for line in sys.stdin if line.strip()]
assert [r["details"]["step"] for r in rows] == [1, 2, 3]
assert len({r["cycle_id"] for r in rows}) == 1
assert rows[-1]["status"] == "verified"
'
echo "PASS"

echo "=== uncorrelated events remain valid ==="
maho_event_emit reliability test.observed observed info \
    'Standalone evidence' '' test '{}' >/dev/null
maho_event_last reliability | python -c '
import json, sys
e = json.load(sys.stdin)
assert e["cycle_id"] is None
'
echo "PASS"

echo "=== invalid cycle fails closed ==="
if MAHO_CYCLE_ID='bad-cycle' maho_event_emit appearance bad observed info bad '' test '{}' >/dev/null 2>&1; then
    fail "invalid cycle id was accepted"
fi
echo "PASS"

echo "ALL CYCLE CONTRACTS PASS"
