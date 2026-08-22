#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export XDG_STATE_HOME="$TMP/state"
export XDG_CACHE_HOME="$TMP/cache"
export XDG_CONFIG_HOME="$TMP/config"
export MAHO_ROOT="$ROOT"
export MAHO_WALLPAPER_POLL=0.05
export PATH="$TMP/bin:$PATH"
export MAHO_TEST_THEME_CALLS="$TMP/theme-calls"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$TMP/bin"

# shellcheck source=../lib/authority.sh
source "$ROOT/lib/authority.sh"
# shellcheck source=../lib/intent.sh
source "$ROOT/lib/intent.sh"
# shellcheck source=../lib/state.sh
source "$ROOT/lib/state.sh"
# shellcheck source=../lib/events.sh
source "$ROOT/lib/events.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

IMAGE="$TMP/wallpaper.jpg"
printf 'fake-image-data\n' > "$IMAGE"

PROVIDER="$TMP/provider"
cat > "$PROVIDER" <<EOF_PROVIDER
#!/usr/bin/env bash
printf '%s\n' '{"version":1,"provider":"test-provider","kind":"image","path":"$IMAGE"}'
EOF_PROVIDER
chmod +x "$PROVIDER"
export MAHO_WALLPAPER_PROVIDER="$PROVIDER"

cat > "$TMP/bin/maho-theme" <<'EOF_THEME'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$MAHO_TEST_THEME_CALLS"
exit 0
EOF_THEME
chmod +x "$TMP/bin/maho-theme"

run_watch_once() {
    local rc
    set +e
    timeout 0.35s "$ROOT/bin/maho-wallpaper" watch >/dev/null 2>&1
    rc=$?
    set -e

    [ "$rc" -eq 124 ] || [ "$rc" -eq 143 ] || fail "watch exited unexpectedly: $rc"
}

calls() {
    if [ -f "$MAHO_TEST_THEME_CALLS" ]; then
        wc -l < "$MAHO_TEST_THEME_CALLS" | tr -d ' '
    else
        printf '0\n'
    fi
}

echo "=== user ownership blocks automation ==="
maho_owner_set appearance.hyprland.borders user >/dev/null
run_watch_once
[ "$(calls)" = "0" ] || fail "theme adapter ran while resource was user-owned"
maho_event_last appearance | python -c '
import json, sys
e = json.load(sys.stdin)
assert e["kind"] == "theme.skipped"
assert e["status"] == "skipped"
assert e["details"]["reason"] == "ownership"
assert e["details"]["owner"] == "user"
'
maho_state_get wallpaper | python -c '
import json, sys
s = json.load(sys.stdin)
assert s["provider"] == "test-provider"
assert s["data"]["kind"] == "image"
'
echo "PASS"

echo "=== maho ownership permits automation ==="
maho_owner_set appearance.hyprland.borders maho >/dev/null
run_watch_once
[ "$(calls)" = "1" ] || fail "theme adapter did not run exactly once"
maho_event_last appearance | python -c '
import json, sys
e = json.load(sys.stdin)
assert e["kind"] == "theme.applied"
assert e["status"] == "verified"
assert e["details"]["kind"] == "image"
'
echo "PASS"

echo "=== user intent disables adaptation ==="
BEFORE="$(calls)"
maho_intent_set appearance.wallpaper.dynamic_theme false >/dev/null
run_watch_once
AFTER="$(calls)"
[ "$BEFORE" = "$AFTER" ] || fail "theme adapter ran while dynamic theme intent was false"
maho_event_last appearance | python -c '
import json, sys
e = json.load(sys.stdin)
assert e["kind"] == "theme.skipped"
assert e["details"]["reason"] == "intent_disabled"
'
echo "PASS"

echo "=== manual action remains authoritative ==="
maho_owner_set appearance.hyprland.borders user >/dev/null
BEFORE="$(calls)"
"$ROOT/bin/maho-wallpaper" adapt image "$IMAGE" >/dev/null 2>&1
AFTER="$(calls)"
[ "$AFTER" -eq $((BEFORE + 1)) ] || fail "manual adaptation was incorrectly blocked by ownership"
echo "PASS"

echo "ALL WALLPAPER POLICY CONTRACTS PASS"
