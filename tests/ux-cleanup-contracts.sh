#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLIP_BACKEND="$ROOT/config/quickshell/maho-clipboard/clipboard.py"
CLIP_STATE="$ROOT/config/quickshell/maho-clipboard/ClipboardState.qml"
CLIP_PANEL="$ROOT/config/quickshell/maho-clipboard/ClipboardPanel.qml"
CLIP_BINDING="$ROOT/config/hypr/maho/integrations/clipboard.lua"
HYPR_MAIN="$ROOT/config/hypr/hyprland.lua"
GENERAL_BINDS="$ROOT/config/hypr/maho/core/binds.lua"
WIRE="$ROOT/bin/maho-ux-wire-clipboard"
LAUNCHER_ROW="$ROOT/config/quickshell/maho-launcher/LauncherResultRow.qml"
LAUNCHER_WINDOW="$ROOT/config/quickshell/maho-launcher/MahoLauncherWindow.qml"
LAUNCHER_SHELL="$ROOT/config/quickshell/maho-launcher/shell.qml"
LAUNCHER_BACKDROP="$ROOT/config/quickshell/maho-launcher/LauncherBackdrop.qml"
LAUNCHER_BIN="$ROOT/bin/maho-launcher"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}

reject_text() {
    local file="$1" needle="$2" message="$3"
    if grep -Fq -- "$needle" "$file"; then
        fail "$message"
    fi
}

printf '%s\n' '=== Clipboard visible text contract ==='
require_text "$CLIP_BACKEND" 'def parse_history_records(output: str)' 'cliphist multiline records are not reconstructed'
require_text "$CLIP_STATE" 'state.items = payload.items || []' 'ClipboardState does not publish backend items'
require_text "$CLIP_PANEL" 'text: String(row.modelData.preview || "")' 'Clipboard delegate is not rendering backend preview text'
require_text "$CLIP_PANEL" 'String(source[i].search || "")' 'Clipboard filtering no longer consumes backend search text'
reject_text "$CLIP_BACKEND" 'logging.' 'clipboard contents could reach ordinary Python logging'

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat > "$TMP/bin/cliphist" <<'EOF_CLIPHIST'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  list)
    printf '9\thello world\n'
    printf '8\tline one\n'
    printf 'line two\n'
    printf 'line three\n'
    printf '7\t\n'
    printf 'useful after leading newline\n'
    printf '6\t   \n'
    ;;
  decode)
    exit 3
    ;;
  *) exit 2 ;;
esac
EOF_CLIPHIST
chmod +x "$TMP/bin/cliphist"

PATH="$TMP/bin:$PATH" python3 "$CLIP_BACKEND" list > "$TMP/list.json"
python3 - "$TMP/list.json" <<'PY'
import json
import pathlib
import sys

payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["available"] is True
rows = {row["id"]: row for row in payload["items"]}
assert rows["9"]["preview"] == "hello world"
assert rows["8"]["preview"] == "line one line two line three"
assert rows["7"]["preview"] == "useful after leading newline"
assert rows["6"]["preview"] == "Empty text"
assert rows["8"]["type"] == "Text"
assert "line two" in rows["8"]["search"]
PY
printf '%s\n' 'PASS  Clipboard short/multiline/leading-newline/whitespace previews'

printf '%s\n' '=== Clipboard permanent hotkey wiring contract ==='
require_text "$CLIP_BINDING" '"SUPER + V"' 'Clipboard integration no longer owns SUPER+V'
require_text "$CLIP_BINDING" '$HOME/.local/bin/maho-clipboard' 'Clipboard bind does not target the permanent command'
require_text "$HYPR_MAIN" 'pcall(require, "maho.integrations.clipboard")' 'Hyprland source does not load the isolated Clipboard integration'
reject_text "$GENERAL_BINDS" 'maho-clipboard' 'Clipboard binding leaked back into the user general binds file'
require_text "$WIRE" 'TARGET="$HYPR_ROOT/maho/integrations/clipboard.lua"' 'live wiring does not install an isolated drop-in'
require_text "$WIRE" 'cp -a "$MAIN" "$backup/hyprland.lua"' 'live wiring does not back up the dirty Hyprland entrypoint'
require_text "$WIRE" 'rollback' 'live wiring has no transactional rollback path'
reject_text "$WIRE" 'maho/core/binds.lua' 'live wiring can overwrite the user general binds file'

WIRE_HOME="$TMP/wire-home"
WIRE_CONFIG="$TMP/wire-config"
WIRE_STATE="$TMP/wire-state"
mkdir -p "$WIRE_HOME/.local/bin" "$WIRE_CONFIG/hypr"
printf '#!/usr/bin/env bash\nexit 0\n' > "$WIRE_HOME/.local/bin/maho-clipboard"
chmod +x "$WIRE_HOME/.local/bin/maho-clipboard"
printf 'require("maho.core.binds")\n' > "$WIRE_CONFIG/hypr/hyprland.lua"
HOME="$WIRE_HOME" XDG_CONFIG_HOME="$WIRE_CONFIG" XDG_STATE_HOME="$WIRE_STATE" MAHO_ROOT="$ROOT" \
    PATH="$TMP/bin:/usr/bin:/bin" bash "$WIRE" install > "$TMP/wire-first.log"
HOME="$WIRE_HOME" XDG_CONFIG_HOME="$WIRE_CONFIG" XDG_STATE_HOME="$WIRE_STATE" MAHO_ROOT="$ROOT" \
    PATH="$TMP/bin:/usr/bin:/bin" bash "$WIRE" install > "$TMP/wire-second.log"
[ -r "$WIRE_CONFIG/hypr/maho/integrations/clipboard.lua" ] || fail 'Clipboard integration was not installed'
[ "$(grep -Fxc 'pcall(require, "maho.integrations.clipboard")' "$WIRE_CONFIG/hypr/hyprland.lua")" -eq 1 ] \
    || fail 'Clipboard loader wiring is not idempotent'
grep -Fq '$HOME/.local/bin/maho-clipboard' "$WIRE_CONFIG/hypr/maho/integrations/clipboard.lua" \
    || fail 'installed Clipboard integration lost permanent command target'
find "$WIRE_STATE/maho/ux-cleanup" -maxdepth 1 -type d -name 'clipboard-wire-*' | grep -q . \
    || fail 'live wiring did not create a rollback snapshot'
printf '%s\n' 'PASS  Clipboard bind is isolated, permanent-path based, additive, and idempotent'

printf '%s\n' '=== Launcher canonical activation contract ==='
require_text "$LAUNCHER_WINDOW" 'backend.activate(resultList.currentItem.modelData)' 'Enter no longer reaches canonical backend activation'
require_text "$LAUNCHER_ROW" 'root.backend.activate(root.modelData)' 'single left click does not reach canonical backend activation'
require_text "$LAUNCHER_ROW" 'acceptedButtons: Qt.LeftButton' 'result row does not explicitly own left click'
require_text "$LAUNCHER_ROW" 'gesturePolicy: TapHandler.ReleaseWithinBounds' 'result click gesture contract drifted'
require_text "$LAUNCHER_ROW" '"path": root.path' 'Files activation payload loses its path role'
require_text "$LAUNCHER_ROW" '"kind": root.kind' 'activation payload loses its kind role'
reject_text "$LAUNCHER_ROW" 'onTapped: root.activated(root.index)' 'mouse click only selects/emits and still depends on parent activation'
printf '%s\n' 'PASS  keyboard and mouse converge on backend.activate'

printf '%s\n' '=== Launcher full-output blur contract ==='
for edge in 'top: true' 'bottom: true' 'left: true' 'right: true'; do
    require_text "$LAUNCHER_BACKDROP" "$edge" "Launcher blur carrier does not cover full output: $edge"
done
require_text "$LAUNCHER_BACKDROP" 'exclusionMode: ExclusionMode.Ignore' 'Edge reservation can still shrink the blur carrier'
require_text "$LAUNCHER_BACKDROP" 'WlrLayershell.layer: WlrLayer.Top' 'blur carrier no longer sits below sharp Overlay surfaces'
require_text "$LAUNCHER_BACKDROP" 'mask: Region {}' 'blur carrier can intercept pointer input'
require_text "$LAUNCHER_BACKDROP" 'WlrLayershell.namespace: "maho-launcher-backdrop"' 'backdrop namespace drifted'
require_text "$LAUNCHER_SHELL" 'LauncherBackdrop {' 'launcher shell no longer owns dedicated blur carrier'
require_text "$LAUNCHER_BIN" 'match = { namespace = "maho-launcher-backdrop" }' 'Hyprland blur is not scoped to the dedicated carrier'
require_text "$LAUNCHER_BIN" 'ignore_alpha = 0.001' 'carrier falls below compositor blur threshold'
reject_text "$LAUNCHER_BIN" 'match = { namespace = "maho-launcher" }' 'sharp interactive Launcher surface is being blurred'
printf '%s\n' 'PASS  full-output backdrop is independent, inputless, and scoped below Edge'

printf '%s\n' 'ALL UX CLEANUP CONTRACTS PASS'
