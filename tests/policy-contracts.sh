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
# shellcheck source=../lib/intent.sh
source "$ROOT/lib/intent.sh"
# shellcheck source=../lib/decision.sh
source "$ROOT/lib/decision.sh"
# shellcheck source=../lib/policy.sh
source "$ROOT/lib/policy.sh"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

WALL="$TMP/wallpaper.jpg"
printf 'test\n' > "$WALL"

STATE="$(python - "$WALL" <<'PY'
import json, sys
print(json.dumps({
    "version": 1,
    "provider": "test-provider",
    "kind": "image",
    "path": sys.argv[1],
}))
PY
)"

echo "=== decision schema ==="
DECISION="$(maho_decision_create test example propose test.resource 'Evidence needs user review' '{"signal":"x"}' '{"operation":"review"}')"
maho_decision_validate "$DECISION" | python -c '
import json, sys
d = json.load(sys.stdin)
assert d["version"] == 1
assert d["domain"] == "test"
assert d["action"] == "propose"
assert d["evidence"]["signal"] == "x"
assert d["desired"]["operation"] == "review"
'
if maho_decision_create test example delete test.resource bad '{}' '{}' >/dev/null 2>&1; then
    fail "mutation-like unknown decision action was accepted"
fi
echo "PASS"

echo "=== wallpaper policy permits owned adaptation ==="
DECISION="$(maho_policy_wallpaper_theme "$STATE")"
printf '%s\n' "$DECISION" | python -c '
import json, sys
d = json.load(sys.stdin)
assert d["domain"] == "appearance"
assert d["policy"] == "wallpaper-theme"
assert d["action"] == "adapt"
assert d["resource"] == "appearance.hyprland.borders"
assert d["evidence"]["owner"] == "maho"
assert d["evidence"]["dynamic_theme"] is True
assert d["desired"]["operation"] == "apply-wallpaper-theme"
assert d["desired"]["mode"] == "dark"
'
echo "PASS"

echo "=== user ownership wins ==="
maho_owner_set appearance.hyprland.borders user >/dev/null
DECISION="$(maho_policy_wallpaper_theme "$STATE")"
printf '%s\n' "$DECISION" | python -c '
import json, sys
d = json.load(sys.stdin)
assert d["action"] == "do-nothing"
assert d["evidence"]["owner"] == "user"
assert "does not own" in d["reason"]
'
echo "PASS"

echo "=== user intent wins ==="
maho_owner_set appearance.hyprland.borders maho >/dev/null
maho_intent_set appearance.wallpaper.dynamic_theme false >/dev/null
DECISION="$(maho_policy_wallpaper_theme "$STATE")"
printf '%s\n' "$DECISION" | python -c '
import json, sys
d = json.load(sys.stdin)
assert d["action"] == "do-nothing"
assert d["evidence"]["dynamic_theme"] is False
assert "disabled by user intent" in d["reason"]
'
echo "PASS"

echo "=== security policy proposes, never mutates ==="
AFFECTED='{"result":"affected","finding_id":"adv-1","finding_source":"test-feed","severity":"critical","confidence":"confirmed","package":"beta","affected_versions":["2.0-1"],"installed_version":"2.0-1","summary":"known affected"}'
DECISION="$(maho_policy_security_package_match "$AFFECTED")"
printf '%s\n' "$DECISION" | python -c '
import json, sys
d = json.load(sys.stdin)
assert d["domain"] == "security"
assert d["action"] == "propose"
assert d["resource"] == "security.packages"
assert d["desired"]["operation"] == "review-security-response"
assert d["evidence"]["confidence"] == "confirmed"
'

SAFE='{"result":"not-affected","finding_id":"adv-2","finding_source":"test-feed","severity":"high","confidence":"high","package":"beta","affected_versions":["9.9-9"],"installed_version":"2.0-1","summary":"other version"}'
DECISION="$(maho_policy_security_package_match "$SAFE")"
printf '%s\n' "$DECISION" | python -c '
import json, sys
d = json.load(sys.stdin)
assert d["action"] == "do-nothing"
assert d["desired"] == {}
'
echo "PASS"

echo "=== policy layer is side-effect free ==="
[ ! -e "$XDG_STATE_HOME/maho/history/events.jsonl" ] || fail "policy evaluation wrote event history"
[ ! -d "$XDG_STATE_HOME/maho/state" ] || fail "policy evaluation published runtime state"
echo "PASS"

echo "ALL POLICY CONTRACTS PASS"
