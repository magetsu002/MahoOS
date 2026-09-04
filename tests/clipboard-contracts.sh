#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/config/quickshell/maho-clipboard/clipboard.py"
PANEL="$ROOT/config/quickshell/maho-clipboard/ClipboardPanel.qml"
THEME="$ROOT/config/quickshell/maho-clipboard/ClipboardTheme.qml"
STATE="$ROOT/config/quickshell/maho-clipboard/ClipboardState.qml"
SHELL="$ROOT/config/quickshell/maho-clipboard/shell.qml"
DECORATIONS="$ROOT/config/hypr/maho/appearance/decorations.lua"
LAUNCHER="$ROOT/bin/maho-clipboard"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

pass() {
    printf 'PASS  %s\n' "$*"
}

for file in "$BACKEND" "$PANEL" "$THEME" "$STATE" "$SHELL" "$DECORATIONS" "$LAUNCHER"; do
    [ -r "$file" ] || fail "missing ${file#$ROOT/}"
done
pass "clipboard files present"

bash -n "$LAUNCHER"
python -m py_compile "$BACKEND"
pass "launcher/backend syntax"

grep -Fq '/.cache/maho/theme/active.json' "$THEME" || fail "theme does not consume active palette"
if grep -Eqi '#(ff|ef|e[0-9a-f]|d[0-9a-f])[0-9a-f]{4}' "$PANEL"; then
    fail "panel contains a bright hardcoded accent-like color"
fi
grep -Fq 'tintedGlass' "$PANEL" || fail "panel does not derive tinted glass from active palette"
grep -Fq 'mix(neutralGlass, accent, 0.018)' "$PANEL" || fail "glass base is too strongly palette-painted"
grep -Fq 'theme.alpha(neutralGlass, 0.72)' "$PANEL" || fail "bluetooth-derived translucent shell material missing"
grep -Fq 'GradientStop { position: 0.00; color: theme.alpha(theme.foreground, 0.032) }' "$PANEL" || fail "neutral reflected cap missing"
if grep -Eq 'neutralReflection|accentBloom|specularSheen' "$PANEL"; then
    fail "clipboard regressed to stacked fake reflection layers"
fi
pass "dynamic palette and bluetooth-material contract"

grep -Fq 'Keys.onPressed' "$PANEL" || fail "keyboard handling missing"
grep -Fq 'Qt.Key_Down' "$PANEL" || fail "Down navigation missing"
grep -Fq 'Qt.Key_Up' "$PANEL" || fail "Up navigation missing"
grep -Fq 'Qt.Key_Escape' "$PANEL" || fail "Escape handling missing"
grep -Fq 'Qt.Key_Return' "$PANEL" || fail "Enter handling missing"
grep -Fq 'root.moveSelection(1)' "$PANEL" || fail "Down key is not wired to selection"
grep -Fq 'root.moveSelection(-1)' "$PANEL" || fail "Up key is not wired to selection"
grep -Fq 'root.activateSelection()' "$PANEL" || fail "Enter key is not wired to activation"
grep -Fq 'searchInput.forceActiveFocus()' "$PANEL" || fail "search field does not claim item focus"
grep -Fq 'focusable: true' "$SHELL" || fail "clipboard window is not permanently keyboard-capable"
grep -Fq 'WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive' "$SHELL" || fail "clipboard window does not claim the Wayland keyboard seat"
grep -Fq 'sequence: "Down"' "$SHELL" || fail "window-level Down shortcut missing"
grep -Fq 'sequence: "Up"' "$SHELL" || fail "window-level Up shortcut missing"
grep -Fq 'sequence: "Return"' "$SHELL" || fail "window-level Return shortcut missing"
grep -Fq 'clipboardSurface.moveSelection(1)' "$SHELL" || fail "window-level Down shortcut not wired"
grep -Fq 'clipboardSurface.moveSelection(-1)' "$SHELL" || fail "window-level Up shortcut not wired"
grep -Fq 'clipboardSurface.activateSelection()' "$SHELL" || fail "window-level Enter shortcut not wired"
if grep -Fq 'clipboardSurface.forceActiveFocus()' "$SHELL"; then
    fail "shell steals item focus away from the search field"
fi
grep -Fq 'hoverEnabled: true' "$PANEL" || fail "mouse hover missing"
grep -Fq 'positionViewAtBeginning()' "$PANEL" || fail "initial selection is not forced into view"
if grep -Fq 'Loading clipboard' "$PANEL"; then
    fail "loading overlay survived refinement"
fi
if grep -Fq 'Enter to copy' "$PANEL"; then
    fail "vibecoded instructional footer survived refinement"
fi
if grep -Fq '⌘F' "$PANEL"; then
    fail "platform-specific search shortcut decoration survived refinement"
fi
pass "interaction contract"

# A second invocation must address the already-running surface in-process. This
# preserves the closing animation and avoids duplicate Quickshell instances.
grep -Fq 'import Quickshell.Io' "$SHELL" || fail "IPC module missing from clipboard shell"
grep -Fq 'IpcHandler {' "$SHELL" || fail "clipboard IPC handler missing"
grep -Fq 'target: "clipboard"' "$SHELL" || fail "clipboard IPC target missing"
grep -Fq 'function toggle(): void { root.toggleOverlay() }' "$SHELL" || fail "clipboard toggle IPC missing"
grep -Fq 'function open(): void { root.showOverlay() }' "$SHELL" || fail "clipboard open IPC missing"
grep -Fq 'function close(): void { root.closeOverlay() }' "$SHELL" || fail "clipboard close IPC missing"
grep -Fq 'quickshell -p "$CONFIG" ipc call clipboard toggle' "$LAUNCHER" || fail "launcher does not toggle the exact running config"
if grep -Eq 'pkill|killall|kill[[:space:]]' "$LAUNCHER"; then
    fail "toggle path kills the UI instead of using IPC"
fi
pass "toggle IPC contract"

# Presentation is a real bottom menu, not a centered modal. The shell continues
# below the viewport, while a single progress curve drives the whole surface.
grep -Fq 'anchors.bottom: parent.bottom' "$SHELL" || fail "clipboard is not anchored to monitor bottom"
grep -Fq 'anchors.horizontalCenter: parent.horizontalCenter' "$SHELL" || fail "clipboard is not centered horizontally"
if grep -Fq 'anchors.centerIn: parent' "$SHELL"; then
    fail "clipboard regressed to centered modal presentation"
fi
grep -Fq 'property real revealProgress: shown ? 1 : 0' "$PANEL" || fail "sheet progress animation missing"
grep -Fq 'y: (1 - root.revealProgress) * 214' "$PANEL" || fail "bottom rise distance missing"
grep -Fq 'Easing.OutExpo' "$PANEL" || fail "native-feeling entry easing missing"
grep -Fq 'height: root.height + 24' "$PANEL" || fail "bottom clipped menu-tail geometry missing"
grep -Fq 'transformOrigin: Item.Bottom' "$PANEL" || fail "bottom-sheet scale origin missing"
if grep -Fq 'contentProgress' "$PANEL"; then
    fail "content is still animated as a separate visual layer"
fi
if grep -Fq 'height: Math.min(240, parent.height * 0.20)' "$SHELL"; then
    fail "fake full-width bottom blur rectangle survived refinement"
fi
pass "bottom-sheet motion contract"

# The QML material is translucent by design; Hyprland provides the actual scene
# blur behind it. ignore_alpha keeps the low-alpha full-screen backdrop from
# blurring the whole desktop. The launcher mirrors the scoped rule for direct
# repository previews where installed compositor config may be older.
grep -Fq 'hl.layer_rule({' "$DECORATIONS" || fail "clipboard compositor layer rule missing"
grep -Fq 'namespace = "maho-clipboard"' "$DECORATIONS" || fail "clipboard blur namespace missing"
grep -Fq 'blur = true' "$DECORATIONS" || fail "clipboard compositor blur disabled"
grep -Fq 'ignore_alpha = 0.16' "$DECORATIONS" || fail "clipboard blur alpha gate missing"
grep -Fq 'xray = false' "$DECORATIONS" || fail "clipboard blur xray override missing"
grep -Fq 'no_anim = true' "$DECORATIONS" || fail "compositor animation can fight QML sheet animation"
grep -Fq 'maho_clipboard_glass_rule' "$LAUNCHER" || fail "repository-direct live blur preview missing"
grep -Fq 'hyprctl eval' "$LAUNCHER" || fail "live blur rule is not applied through current Hyprland Lua runtime"
pass "compositor glass contract"

if grep -Eq 'wl-paste[[:space:]].*--watch|cliphist[[:space:]]+store|sqlite|CREATE TABLE' "$BACKEND" "$PANEL" "$THEME" "$STATE" "$SHELL" "$LAUNCHER"; then
    fail "clipboard frontend creates a watcher or duplicate store"
fi
if grep -Eq 'shell=True|os\.system|subprocess\.(run|Popen)\([^\n]*shell[[:space:]]*=' "$BACKEND"; then
    fail "backend uses shell execution"
fi
if grep -Fq 'maho-clipboard.log' "$LAUNCHER"; then
    fail "launcher persists a clipboard UI debug log"
fi
pass "backend preservation/security contract"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"

cat > "$TMP/bin/cliphist" <<'EOF_CLIPHIST'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  list)
    printf '7\tcd ~/Projects/Maho-OS\n'
    printf '6\thttps://github.com/maho-os/maho-link\n'
    printf '5\t[[ binary data 782 KiB png 1270x868 ]]\n'
    printf '4\tordinary clipboard text\n'
    ;;
  decode)
    [ "${2:-}" = "7" ] || exit 4
    printf 'exact restored bytes'
    ;;
  *) exit 2 ;;
esac
EOF_CLIPHIST
chmod +x "$TMP/bin/cliphist"

cat > "$TMP/bin/wl-copy" <<'EOF_WLCOPY'
#!/usr/bin/env bash
set -euo pipefail
cat > "${MAHO_TEST_CAPTURE:?}"
EOF_WLCOPY
chmod +x "$TMP/bin/wl-copy"

LIST_JSON="$(PATH="$TMP/bin:$PATH" python "$BACKEND" list)"
python - "$LIST_JSON" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
assert payload["available"] is True
assert [item["type"] for item in payload["items"]] == ["Command", "Link", "Image", "Text"]
assert payload["items"][2]["preview"] == "[Image] PNG · 782 KiB · 1270×868"
assert all("selection" not in item for item in payload["items"])
PY
pass "history preview classification"

CAPTURE="$TMP/restored.bin"
MAHO_TEST_CAPTURE="$CAPTURE" PATH="$TMP/bin:$PATH" python "$BACKEND" select 7 > "$TMP/select.json"
python - "$TMP/select.json" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
assert payload == {"ok": True, "error": ""}
PY
[ "$(cat "$CAPTURE")" = 'exact restored bytes' ] || fail "selection bytes were not forwarded to wl-copy"
pass "selection restore path"

printf 'PASS  clipboard contracts\n'