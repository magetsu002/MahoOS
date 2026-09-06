#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CLIP_BACKEND="$ROOT/config/quickshell/maho-clipboard/clipboard.py"
CLIP_STATE="$ROOT/config/quickshell/maho-clipboard/ClipboardState.qml"
CLIP_PANEL="$ROOT/config/quickshell/maho-clipboard/ClipboardPanel.qml"
CLIP_PIN_GLYPH="$ROOT/config/quickshell/maho-clipboard/ClipboardPinGlyph.qml"
LAUNCHER_ROW="$ROOT/config/quickshell/maho-launcher/LauncherResultRow.qml"
LAUNCHER_WINDOW="$ROOT/config/quickshell/maho-launcher/MahoLauncherWindow.qml"
LAUNCHER_SHELL="$ROOT/config/quickshell/maho-launcher/shell.qml"
LAUNCHER_BACKDROP="$ROOT/config/quickshell/maho-launcher/LauncherBackdrop.qml"
LAUNCHER_BIN="$ROOT/bin/maho-launcher"
MAHO_SHELL="$ROOT/config/quickshell/maho-shell/shell.qml"

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
reject_text "$CLIP_BACKEND" 'print(preview)' 'clipboard preview could leak to ordinary stdout diagnostics'

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

printf '%s\n' '=== Clipboard pin discoverability contract ==='
require_text "$CLIP_PANEL" 'ClipboardPinGlyph {' 'clipboard row pin affordance is missing'
require_text "$CLIP_PANEL" 'root.clipboardState.togglePin(row.modelData)' 'clipboard pin affordance is not actionable'
require_text "$CLIP_PIN_GLYPH" 'import QtQuick.Shapes' 'pin is not rendered through proportional vector geometry'
require_text "$CLIP_PIN_GLYPH" 'PathSvg {' 'pin vector outline is missing'
require_text "$CLIP_PIN_GLYPH" 'Math.max(0.92, glyphColor.a)' 'unpinned glyph can fade below readable opacity'
require_text "$CLIP_PIN_GLYPH" 'scale: Math.min(root.width, root.height) / 18' 'pin can stretch instead of preserving its aspect ratio'
reject_text "$CLIP_PIN_GLYPH" 'rotation: 64' 'legacy rotated-rectangle pin geometry returned'
printf '%s\n' 'PASS  Clipboard pin action uses proportional visible vector geometry'

printf '%s\n' '=== Launcher canonical activation contract ==='
require_text "$LAUNCHER_WINDOW" 'function activateItem(index)' 'Launcher has no canonical activation entry point'
require_text "$LAUNCHER_WINDOW" 'const authoritativeRow = backend.itemAt(index)' 'activation does not resolve the current authoritative row'
require_text "$LAUNCHER_WINDOW" 'backend.activate(authoritativeRow)' 'canonical activation does not reach the backend'
require_text "$LAUNCHER_WINDOW" 'activateItem(resultList.currentIndex)' 'Enter no longer reaches canonical activation'
require_text "$LAUNCHER_WINDOW" 'root.activateItem(rowIndex)' 'single left click does not reach canonical activation'
require_text "$LAUNCHER_ROW" 'acceptedButtons: Qt.LeftButton' 'result row does not explicitly own left click'
require_text "$LAUNCHER_ROW" 'gesturePolicy: TapHandler.ReleaseWithinBounds' 'result click gesture contract drifted'
require_text "$LAUNCHER_ROW" 'root.hovered(root.index)' 'click does not update visual selection before activation'
require_text "$LAUNCHER_ROW" 'root.activated(root.index)' 'row does not publish its clicked index'
reject_text "$LAUNCHER_ROW" 'modelData' 'delegate-local model data can still bypass authoritative lookup'
printf '%s\n' 'PASS  keyboard and mouse converge on authoritative activateItem'

printf '%s\n' '=== Maho Edge launcher routing contract ==='
require_text "$MAHO_SHELL" '/.local/bin/maho-launcher' 'Maho Edge does not route Launcher through the managed current runtime'
reject_text "$MAHO_SHELL" 'maho-rice-launcher' 'Maho Edge still routes to the obsolete rice launcher'
printf '%s\n' 'PASS  Maho Edge and keyboard route to the managed Maho Launcher'

printf '%s\n' '=== Launcher full-output blur contract ==='
for edge in 'top: true' 'bottom: true' 'left: true' 'right: true'; do
    require_text "$LAUNCHER_BACKDROP" "$edge" "Launcher blur carrier does not cover full output: $edge"
done
require_text "$LAUNCHER_BACKDROP" 'exclusionMode: ExclusionMode.Ignore' 'Edge reservation can still shrink the blur carrier'
require_text "$LAUNCHER_WINDOW" 'exclusionMode: ExclusionMode.Ignore' 'Edge reservation can still shrink or offset the Launcher interaction plane'
reject_text "$LAUNCHER_WINDOW" 'exclusiveZone:' 'explicit Launcher exclusiveZone can reset Ignore semantics and reintroduce the top reservation seam'
require_text "$LAUNCHER_BACKDROP" 'WlrLayershell.layer: WlrLayer.Top' 'blur carrier no longer sits below sharp Overlay surfaces'
require_text "$LAUNCHER_BACKDROP" 'mask: Region {}' 'blur carrier can intercept pointer input'
require_text "$LAUNCHER_BACKDROP" 'WlrLayershell.namespace: "maho-launcher-backdrop"' 'backdrop namespace drifted'
require_text "$LAUNCHER_SHELL" 'LauncherBackdrop {' 'launcher shell no longer owns dedicated blur carrier'
require_text "$LAUNCHER_BIN" 'match = { namespace = "maho-launcher-backdrop" }' 'Hyprland blur is not scoped to the dedicated carrier'
require_text "$LAUNCHER_BIN" 'ignore_alpha = 0.001' 'carrier falls below compositor blur threshold'
reject_text "$LAUNCHER_BIN" 'match = { namespace = "maho-launcher" }' 'sharp interactive Launcher surface is being blurred'
printf '%s\n' 'PASS  full-output backdrop and interaction plane both ignore Edge reservation'

printf '%s\n' 'ALL UX CLEANUP CONTRACTS PASS'
