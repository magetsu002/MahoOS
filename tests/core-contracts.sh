#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CONFIG_HOME"

# shellcheck source=../lib/authority.sh
source "$ROOT/lib/authority.sh"
# shellcheck source=../lib/state.sh
source "$ROOT/lib/state.sh"
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"
# shellcheck source=../lib/intent.sh
source "$ROOT/lib/intent.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

assert_eq() {
    local expected="$1"
    local actual="$2"
    local label="$3"

    [ "$expected" = "$actual" ] ||
        fail "$label: expected '$expected', got '$actual'"
}

echo "=== authority ==="
assert_eq user "$(maho_owner_get test.unknown)" "unknown ownership safety default"
maho_owner_set test.resource maho >/dev/null
assert_eq maho "$(maho_owner_get test.resource)" "user ownership override"
maho_owner_set test.resource integration >/dev/null
assert_eq integration "$(maho_owner_get test.resource)" "integration ownership"
maho_owner_unset test.resource
assert_eq user "$(maho_owner_get test.resource)" "ownership unset safety default"
echo "PASS"

echo "=== intent ==="
assert_eq true "$(maho_intent_get appearance.wallpaper.dynamic_theme)" "default dynamic theme intent"
assert_eq '"dark"' "$(maho_intent_get appearance.theme.mode)" "default theme mode"
maho_intent_set appearance.wallpaper.dynamic_theme false >/dev/null
assert_eq false "$(maho_intent_get appearance.wallpaper.dynamic_theme)" "user intent override"
if maho_intent_bool appearance.wallpaper.dynamic_theme; then
    fail "false boolean intent evaluated true"
fi
maho_intent_unset appearance.wallpaper.dynamic_theme
assert_eq true "$(maho_intent_get appearance.wallpaper.dynamic_theme)" "intent unset restores default"
maho_intent_bool appearance.wallpaper.dynamic_theme || fail "true boolean intent evaluated false"
echo "PASS"

echo "=== normalized state ==="
maho_state_publish wallpaper test-provider '{"kind":"image","path":"/tmp/example.jpg"}' >/dev/null
maho_state_get wallpaper | python -c '
import json, sys
state = json.load(sys.stdin)
assert state["version"] == 1
assert state["domain"] == "wallpaper"
assert state["provider"] == "test-provider"
assert state["data"]["kind"] == "image"
assert state["data"]["path"] == "/tmp/example.jpg"
assert state["observed_at"].endswith("Z")
'
echo "PASS"

echo "=== event history ==="
FIRST="$(
    maho_event_emit \
        appearance \
        wallpaper.changed \
        observed \
        info \
        'Wallpaper changed' \
        appearance.hyprland.borders \
        test-provider \
        '{"kind":"image"}'
)"

SECOND="$(
    maho_event_emit \
        appearance \
        theme.applied \
        verified \
        low \
        'Theme adaptation verified' \
        appearance.hyprland.borders \
        hyprland \
        '{"adapter":"hyprland-borders"}'
)"

[ "$FIRST" != "$SECOND" ] || fail "event ids must be unique"

maho_event_last appearance | python -c '
import json, sys
event = json.load(sys.stdin)
assert event["version"] == 1
assert event["domain"] == "appearance"
assert event["kind"] == "theme.applied"
assert event["status"] == "verified"
assert event["details"]["adapter"] == "hyprland-borders"
'

maho_event_show "$FIRST" | python -c '
import json, sys
event = json.load(sys.stdin)
assert event["kind"] == "wallpaper.changed"
assert event["status"] == "observed"
'

if maho_event_emit appearance bad observed impossible 'bad risk' '' '' '{}' >/dev/null 2>&1; then
    fail "invalid risk accepted"
fi

assert_eq 600 "$(stat -c '%a' "$MAHO_EVENT_LOG")" "event log permissions"
assert_eq 700 "$(stat -c '%a' "$(dirname "$MAHO_EVENT_LOG")")" "event history directory permissions"

echo "PASS"

echo "=== event history tolerates partial records ==="
printf '%s' '{"version":1,"id":"partial"' >> "$MAHO_EVENT_LOG"
TAIL_OUTPUT="$(maho_event_tail 10)" || fail "event history failed on a partial JSONL record"
printf '%s\n' "$TAIL_OUTPUT" | grep -q 'theme.applied' || fail "valid history disappeared after partial record"
maho_event_last appearance | python -c '
import json, sys
event = json.load(sys.stdin)
assert event["kind"] == "theme.applied"
assert event["status"] == "verified"
'
echo "PASS"

echo "=== registry validation ==="
maho_owner_validate_file "$ROOT/config/ownership.json"
maho_intent_validate_file "$ROOT/config/intent.json"
python -m json.tool "$ROOT/config/ownership.json" >/dev/null
python -m json.tool "$ROOT/config/intent.json" >/dev/null
echo "PASS"

echo "=== Palette V2 behavior and compatibility ==="
python "$ROOT/tests/palette-v2.py"

echo "=== Maho Update authority ==="
python "$ROOT/tests/test_maho_update_state.py"
python "$ROOT/tests/test_maho_update_discovery.py"
python "$ROOT/tests/test_maho_update_staging.py"
python "$ROOT/tests/test_maho_update_preparation.py"
python "$ROOT/tests/test_maho_update_maintenance.py"
python "$ROOT/tests/test_maho_update_transaction.py"
python "$ROOT/tests/test_maho_update_receipts.py"
python "$ROOT/tests/test_maho_update_cli.py"
bash "$ROOT/tests/maho-update-product-contracts.sh"
python "$ROOT/tests/test_guardian_update.py"
python "$ROOT/tests/test_maho_update_adversarial.py"
python "$ROOT/tests/test_maho_update_native.py"

echo "=== Trust, generations, admission, and independent recovery ==="
python "$ROOT/tests/test_trust_identity.py"
python "$ROOT/tests/test_generation_v2.py"
python "$ROOT/tests/test_kernel_generation.py"
python "$ROOT/tests/test_guardian_offline_recovery.py"
bash "$ROOT/tests/guardian-recovery-r1.sh"
python "$ROOT/tests/guardian-recovery-r2.py"
python "$ROOT/tests/test_guardian_recovery_r3.py"
python "$ROOT/tests/test_guardian_recovery_r3_executor.py"
python "$ROOT/tests/test_guardian_recovery_r3_postboot.py"
python "$ROOT/tests/test_guardian_recovery_r3_native.py"
python "$ROOT/tests/test_guardian_recovery_tui.py"
python "$ROOT/tests/test_guardian_admission.py"
python "$ROOT/tests/test_guardian_native_admission.py"
python "$ROOT/tests/test_guardian_revocation.py"
python "$ROOT/tests/test_guardian_revocation_recovery.py"
python "$ROOT/tests/test_guardian_trust_status.py"

echo "=== Adaptive policy A1-A15 ==="
for test in "$ROOT"/tests/test_adaptive_*.py; do
  python "$test"
done

echo "ALL CORE CONTRACTS PASS"
