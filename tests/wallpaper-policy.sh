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
export PATH="$TMP/bin:$PATH"
export MAHO_TEST_THEME_CALLS="$TMP/theme-calls"
export MAHO_TEST_ADAPTER_STATE="$TMP/adapter-state.json"
export MAHO_ADAPTER_REGISTRY="$TMP/adapters.json"

mkdir -p "$HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME" "$XDG_CONFIG_HOME" "$TMP/bin"
printf '%s\n' '{"operation":"initial","value":"old"}' > "$MAHO_TEST_ADAPTER_STATE"

cat > "$MAHO_ADAPTER_REGISTRY" <<'JSON'
{
  "version": 1,
  "operations": {
    "apply-wallpaper-theme": {
      "adapter": "tests/fixtures/fake-adapter.sh",
      "domain": "appearance",
      "resource": "appearance.hyprland.borders"
    }
  }
}
JSON

source "$ROOT/lib/authority.sh"
source "$ROOT/lib/intent.sh"
source "$ROOT/lib/state.sh"
source "$ROOT/lib/events.sh"

fail() { echo "FAIL: $*" >&2; exit 1; }

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

run_once() {
    bash "$ROOT/bin/maho-wallpaper" once >/dev/null
}

run_reconcile() {
    bash "$ROOT/bin/maho-wallpaper" reconcile >/dev/null
}

expected_adapter_state() {
    python - "$IMAGE" <<'PY'
import json,os,sys
print(json.dumps({
    "operation":"apply-wallpaper-theme",
    "kind":"image",
    "path":os.path.realpath(sys.argv[1]),
    "mode":"dark",
},sort_keys=True))
PY
}

echo "=== user ownership blocks automation ==="
maho_owner_set appearance.hyprland.borders user >/dev/null
BEFORE="$(cat "$MAHO_TEST_ADAPTER_STATE")"
run_once
[ "$(cat "$MAHO_TEST_ADAPTER_STATE")" = "$BEFORE" ] || fail "adapter ran while resource was user-owned"
maho_event_last appearance | python -c '
import json,sys
e=json.load(sys.stdin)
if e["kind"] != "policy.decision" or e["status"] != "skipped" or "does not own" not in e["summary"]:
    raise SystemExit("unexpected user-owned event: "+json.dumps(e,sort_keys=True))
'
maho_state_get wallpaper | python -c '
import json,sys
s=json.load(sys.stdin)
assert s["provider"] == "test-provider"
assert s["data"]["kind"] == "image"
'
echo "PASS"

echo "=== maho ownership permits generic adaptation ==="
maho_owner_set appearance.hyprland.borders maho >/dev/null
run_once
[ "$(cat "$MAHO_TEST_ADAPTER_STATE")" = "$(expected_adapter_state)" ] || fail "generic wallpaper adapter did not reach desired state"
LAST="$(maho_event_last appearance)"
printf '%s\n' "$LAST" | python -c '
import json,sys
e=json.load(sys.stdin)
if e["kind"] != "adaptation.completed" or e["status"] != "verified":
    raise SystemExit("unexpected completion event: "+json.dumps(e,sort_keys=True))
'
CYCLE="$(printf '%s\n' "$LAST" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
kinds=[r["kind"] for r in rows]
expected=["wallpaper.changed","policy.decision","authorization.allowed","adapter.capture","adapter.apply","adapter.verify","adaptation.completed"]
if kinds != expected:
    raise SystemExit("unexpected cycle kinds: "+repr(kinds))
'
echo "PASS"

echo "=== healthy reconciliation is read-only ==="
BEFORE_HASH="$(sha256sum "$MAHO_TEST_ADAPTER_STATE" | cut -d' ' -f1)"
run_reconcile
AFTER_HASH="$(sha256sum "$MAHO_TEST_ADAPTER_STATE" | cut -d' ' -f1)"
[ "$BEFORE_HASH" = "$AFTER_HASH" ] || fail "healthy reconciliation rewrote desired state"
LAST="$(maho_event_last appearance)"
printf '%s\n' "$LAST" | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "adaptation.satisfied"
assert e["status"] == "verified"
'
CYCLE="$(printf '%s\n' "$LAST" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
assert [r["kind"] for r in rows] == [
    "wallpaper.reconcile",
    "policy.decision",
    "authorization.allowed",
    "adaptation.satisfied",
]
'
echo "PASS"

echo "=== reconciliation repairs drift ==="
printf '%s\n' '{"operation":"drift","value":"wrong"}' > "$MAHO_TEST_ADAPTER_STATE"
run_reconcile
[ "$(cat "$MAHO_TEST_ADAPTER_STATE")" = "$(expected_adapter_state)" ] || fail "reconciliation did not repair drift"
LAST="$(maho_event_last appearance)"
printf '%s\n' "$LAST" | python -c '
import json,sys
e=json.load(sys.stdin)
assert e["kind"] == "adaptation.completed"
assert e["status"] == "verified"
'
CYCLE="$(printf '%s\n' "$LAST" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
maho_event_cycle "$CYCLE" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
kinds=[r["kind"] for r in rows]
assert kinds[0] == "wallpaper.reconcile"
assert "adapter.apply" in kinds
assert "adapter.verify" in kinds
assert kinds[-1] == "adaptation.completed"
'
echo "PASS"

echo "=== user intent disables adaptation ==="
maho_intent_set appearance.wallpaper.dynamic_theme false >/dev/null
printf '%s\n' '{"operation":"sentinel","value":"stable"}' > "$MAHO_TEST_ADAPTER_STATE"
run_once
python - "$MAHO_TEST_ADAPTER_STATE" <<'PY'
import json,sys
from pathlib import Path
assert json.loads(Path(sys.argv[1]).read_text())["operation"] == "sentinel"
PY
maho_event_last appearance | python -c '
import json,sys
e=json.load(sys.stdin)
if e["kind"] != "policy.decision" or e["status"] != "skipped" or "disabled by user intent" not in e["summary"]:
    raise SystemExit("unexpected intent-disabled event: "+json.dumps(e,sort_keys=True))
'
echo "PASS"

echo "=== manual action remains authoritative ==="
maho_owner_set appearance.hyprland.borders user >/dev/null
BEFORE=0
[ ! -f "$MAHO_TEST_THEME_CALLS" ] || BEFORE="$(wc -l < "$MAHO_TEST_THEME_CALLS" | tr -d ' ')"
bash "$ROOT/bin/maho-wallpaper" adapt image "$IMAGE" >/dev/null 2>&1
AFTER="$(wc -l < "$MAHO_TEST_THEME_CALLS" | tr -d ' ')"
[ "$AFTER" -eq $((BEFORE + 1)) ] || fail "manual adaptation was incorrectly blocked by ownership"
echo "PASS"

echo "ALL WALLPAPER POLICY CONTRACTS PASS"
