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

run_watch_once() {
    local rc
    set +e
    timeout 1s bash "$ROOT/bin/maho-wallpaper" watch >/dev/null 2>&1
    rc=$?
    set -e
    [ "$rc" -eq 124 ] || [ "$rc" -eq 143 ] || fail "watch exited unexpectedly: $rc"
}

echo "=== user ownership blocks automation ==="
maho_owner_set appearance.hyprland.borders user >/dev/null
BEFORE="$(cat "$MAHO_TEST_ADAPTER_STATE")"
run_watch_once
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
run_watch_once
python - "$MAHO_TEST_ADAPTER_STATE" "$IMAGE" <<'PY'
import json,os,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
expected={"operation":"apply-wallpaper-theme","kind":"image","path":os.path.realpath(sys.argv[2]),"mode":"dark"}
if d != expected:
    raise SystemExit(f"adapter state mismatch: expected={expected!r} actual={d!r}")
PY
LAST="$(maho_event_last appearance)"
printf '%s\n' "$LAST" | python -c '
import json,sys
e=json.load(sys.stdin)
if e["kind"] != "adaptation.completed" or e["status"] != "verified":
    raise SystemExit("unexpected completion event: "+json.dumps(e,sort_keys=True))
'
CYCLE="$(printf '%s\n' "$LAST" | python -c 'import json,sys; print(json.load(sys.stdin)["cycle_id"])')"
CYCLE_ROWS="$(maho_event_cycle "$CYCLE")"
printf '%s\n' "$CYCLE_ROWS" | python -c '
import json,sys
rows=[json.loads(line) for line in sys.stdin if line.strip()]
kinds=[r["kind"] for r in rows]
required=["wallpaper.changed","authorization.allowed","adapter.capture","adapter.apply","adapter.verify","adaptation.completed"]
missing=[k for k in required if k not in kinds]
if missing or kinds[0] != "wallpaper.changed" or kinds[-1] != "adaptation.completed":
    raise SystemExit("unexpected cycle kinds: "+repr(kinds)+" missing="+repr(missing))
'
echo "PASS"

echo "=== user intent disables adaptation ==="
maho_intent_set appearance.wallpaper.dynamic_theme false >/dev/null
printf '%s\n' '{"operation":"sentinel","value":"stable"}' > "$MAHO_TEST_ADAPTER_STATE"
run_watch_once
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
