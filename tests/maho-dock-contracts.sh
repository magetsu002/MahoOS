#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
QML="$ROOT/config/quickshell/maho-shell"
DOCK="$QML/MahoDock.qml"
DOCK_ENTRY="$QML/dock-shell.qml"
PREVIEW="$QML/MahoDockPreviewCard.qml"
MODEL="$QML/MahoDockModel.qml"
STATE="$QML/MahoDockState.qml"
THEME="$QML/MahoTheme.qml"
WRAPPER="$ROOT/bin/maho-dock"
APP_MODEL="$ROOT/lib/maho_app_model.py"
LAUNCHER_BACKEND="$ROOT/lib/maho_launcher_backend.py"
DECORATIONS="$ROOT/config/hypr/maho/appearance/decorations.lua"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject_text() { if grep -Fiq -- "$2" "$1"; then fail "$3"; fi; }

echo "=== independent Dock lifecycle ==="
require_text "$DOCK_ENTRY" 'ShellId maho-dock' "Dock has no independent Quickshell identity"
require_text "$DOCK_ENTRY" 'MahoDockState {' "Dock entrypoint has no persistent state"
require_text "$DOCK_ENTRY" 'MahoDockModel {' "Dock entrypoint has no app/window model"
require_text "$DOCK_ENTRY" 'MahoDock {' "Dock entrypoint has no visual surface"
reject_text "$THEME" 'MahoDockRuntime {' "MahoTheme still owns Dock lifecycle"
require_text "$WRAPPER" "maho-shell/dock-shell.qml" "Dock wrapper does not target only the Dock entrypoint"
reject_text "$WRAPPER" "pkill -f 'quickshell.*maho-shell/shell.qml'" "Dock stop can kill Maho Edge"
require_text "$WRAPPER" 'maho-dock.lock' "Dock has no independent singleton lock"
echo PASS

echo "=== bounded stable carrier ==="
require_text "$DOCK" 'bottom: true' "Dock is not bottom anchored"
reject_text "$DOCK" 'top: true' "Dock unexpectedly spans the top edge"
reject_text "$DOCK" 'left: true' "Dock unexpectedly spans the left edge"
reject_text "$DOCK" 'right: true' "Dock unexpectedly spans the right edge"
require_text "$DOCK" 'bottom: 2' "Dock optical bottom margin drifted away from the screen edge"
require_text "$DOCK" 'implicitWidth: 720' "Dock no longer uses the stable preview carrier"
require_text "$DOCK" 'implicitHeight: 438' "Dock carrier no longer has room for the adaptive preview stage"
require_text "$DOCK" 'previewHeight: 324' "Dock preview stage regressed to the cramped layout"
require_text "$DOCK" 'restingDockWidth: Math.max(320, dockRow.implicitWidth + 46)' "resting Dock is not icon-count driven"
require_text "$DOCK" 'item: root.previewOpen || root.previewProgress > 0.02 ? materialBounds : dockShell' "Dock input is not bounded to visible material state"
require_text "$DOCK" 'exclusionMode: ExclusionMode.Ignore' "Dock reserves compositor space"
require_text "$DOCK" 'WlrLayershell.namespace: "maho-dock"' "Dock has no scoped layer namespace"
echo PASS

echo "=== adaptive premium glass ==="
require_text "$THEME" 'semanticSurfaceElevated' "shared theme does not expose Palette V2 semantic material"
require_text "$DOCK" 'darkGlassLift' "Dock lacks dark-wallpaper material compensation"
require_text "$DOCK" 'liftedNeutral' "Dock does not lift dark glass toward a readable neutral"
require_text "$DOCK" 'shellOuterRim' "Dock lost the outer optical rim"
require_text "$DOCK" 'shellInnerRim' "Dock lost layered rim depth"
require_text "$DOCK" 'shellSpecular' "Dock lost the optical top reflection"
require_text "$DOCK" 'shellReflection' "Dock lost the broad reflective layer"
require_text "$DOCK" 'id: dockInnerWell' "Dock icons no longer sit in a nested glass well"
require_text "$DECORATIONS" 'match = { namespace = "maho-dock" }' "Dock compositor blur is not namespace scoped"
require_text "$DECORATIONS" 'blur = true' "Dock compositor blur is missing"
require_text "$DECORATIONS" 'xray = false' "Dock blur ignores the real background stack"
reject_text "$DOCK" '#ff0000' "Dock hardcodes target-wallpaper red"
echo PASS

echo "=== coordinated motion and reliable dismissal ==="
require_text "$DOCK" 'property real previewProgress: previewOpen ? 1 : 0' "preview reveal has no single material progress authority"
require_text "$DOCK" 'interval: 620' "window preview hover intent drifted"
require_text "$DOCK" 'readonly property bool pointerInsideMaterial' "preview dismissal still relies on stale manual hover bookkeeping"
require_text "$DOCK" 'dockSurfaceHover.hovered || previewHover.hovered' "Dock and preview do not share one pointer-inside authority"
require_text "$DOCK" 'if (!root.pointerInsideMaterial)' "preview dismissal does not collapse after leaving the whole material"
require_text "$DOCK" 'id: hoverLens' "Dock has no shared sliding hover material"
reject_text "$DOCK" 'property bool dockHovering' "stale dockHovering bookkeeping can wedge the preview open"
reject_text "$DOCK" 'SpringAnimation' "Dock reintroduced bouncy motion"
echo PASS

echo "=== native adaptive window preview ==="
require_text "$PREVIEW" 'ScreencopyView {' "Dock preview does not use native screencopy"
require_text "$PREVIEW" 'top.handle || top.wayland || null' "Dock preview does not prefer an exported toplevel handle"
require_text "$PREVIEW" 'visible: !capture.hasContent' "Dock preview has no capture readiness fallback"
require_text "$PREVIEW" 'Preview unavailable' "capture failure still renders as unexplained blank content"
require_text "$DOCK" 'if (!previewItem || !previewItem.windows)' "Dock preview still relies on brittle Array.isArray gating"
require_text "$DOCK" 'windows.slice(0, 3)' "Dock preview does not bound selected app windows"
require_text "$DOCK" 'previewTargetWidth' "preview shell does not adapt to window count"
require_text "$DOCK" 'previewCardWidth' "window cards do not adapt to group size"
require_text "$DOCK" 'previewCardHeight' "window cards do not adapt to group size"
require_text "$DOCK" 'id: previewStage' "preview cards have no dedicated collision-free stage"
require_text "$DOCK" 'anchors.bottom: previewActions.top' "preview stage can collide with the footer"
require_text "$DOCK" 'cardWidth: root.previewCardWidth' "adaptive card width is not applied"
require_text "$DOCK" 'cardHeight: root.previewCardHeight' "adaptive card height is not applied"
require_text "$PREVIEW" 'id: previewViewport' "window capture has no dedicated viewport"
require_text "$PREVIEW" 'id: titleRail' "window title still overlays the live capture"
reject_text "$PREVIEW" 'width: 198' "preview card is still hardcoded to postage-stamp size"
echo PASS

echo "=== user pinning contract ==="
require_text "$DOCK" 'Qt.RightButton' "Dock has no direct pin/unpin interaction"
require_text "$DOCK" 'function togglePin(item)' "Dock has no pin toggle action"
require_text "$DOCK" 'dockModel.pinItem(item)' "Dock cannot pin an identified running app"
require_text "$DOCK" 'dockModel.unpinItem(item)' "Dock cannot unpin an app"
require_text "$DOCK" 'pinFeedbackText' "pin/unpin has no visible confirmation"
require_text "$STATE" 'Quickshell.statePath("maho-dock.json")' "Dock pins do not persist in Maho state"
require_text "$STATE" 'atomicWrites: true' "Dock state writes are not atomic"
require_text "$MODEL" 'function pinItem(item)' "Dock model lost pin API"
require_text "$MODEL" 'function unpinItem(item)' "Dock model lost unpin API"
echo PASS

echo "=== shared application identity ==="
require_text "$LAUNCHER_BACKEND" 'from maho_app_model import (' "Launcher does not use the shared Maho app model"
require_text "$APP_MODEL" '"startupWmClass"' "shared app model does not expose StartupWMClass"
require_text "$APP_MODEL" '"aliases"' "shared app model does not publish canonical aliases"
require_text "$MODEL" 'root.aliasToId[normalized]' "Dock does not match windows through canonical aliases"
require_text "$MODEL" 'clean(ipc.class)' "Dock does not consider Hyprland class"
require_text "$MODEL" 'clean(ipc.initialClass)' "Dock does not consider Hyprland initialClass"
require_text "$MODEL" 'toplevel.wayland.appId' "Dock does not consider Wayland appId"
python3 - "$MODEL" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
start = text.index("function identityForToplevel")
end = text.index("function windowRecord", start)
identity = text[start:end]
if ".title" in identity or "title)" in identity:
    raise SystemExit("FAIL: Dock matches app identity using window title")
PY
echo PASS

echo "=== event-driven Hyprland session model ==="
require_text "$MODEL" 'Hyprland.toplevels.values' "Dock does not consume Quickshell Hyprland toplevels"
require_text "$MODEL" 'function onRawEvent(event)' "Dock is not driven by Hyprland events"
require_text "$MODEL" 'Hyprland.refreshToplevels()' "Dock cannot refresh authoritative window metadata"
require_text "$MODEL" 'targetWorkspace.activate()' "Dock does not switch to target workspace"
require_text "$MODEL" 'Hyprland.dispatch("focuswindow address:" + address)' "Dock does not focus the exact window"
reject_text "$MODEL" 'repeat: true' "Dock introduced continuous window polling"
echo PASS

echo "ALL MAHO DOCK M1.10 CONTRACTS PASS"
