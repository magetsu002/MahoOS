#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
QML="$ROOT/config/quickshell/maho-shell"
DOCK="$QML/MahoDock.qml"
PREVIEW="$QML/MahoDockPreviewCard.qml"
MODEL="$QML/MahoDockModel.qml"
STATE="$QML/MahoDockState.qml"
RUNTIME="$QML/MahoDockRuntime.qml"
THEME="$QML/MahoTheme.qml"
APP_MODEL="$ROOT/lib/maho_app_model.py"
LAUNCHER_BACKEND="$ROOT/lib/maho_launcher_backend.py"
DECORATIONS="$ROOT/config/hypr/maho/appearance/decorations.lua"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject_text() { if grep -Fiq -- "$2" "$1"; then fail "$3"; fi; }

echo "=== same-process shell architecture ==="
require_text "$THEME" 'MahoDockRuntime {' "Maho Shell does not bootstrap Dock"
require_text "$RUNTIME" 'MahoDockState {' "Dock pin state missing from shell runtime"
require_text "$RUNTIME" 'MahoDockModel {' "Dock app/window model missing from shell runtime"
require_text "$RUNTIME" 'MahoDock {' "Dock visual surface missing from shell runtime"
reject_text "$RUNTIME" 'Process {' "Dock runtime created a separate daemon/process"
echo PASS

echo "=== bounded stable carrier ==="
require_text "$DOCK" 'bottom: true' "Dock is not bottom anchored"
reject_text "$DOCK" 'top: true' "Dock unexpectedly spans the top edge"
reject_text "$DOCK" 'left: true' "Dock unexpectedly spans the left edge"
reject_text "$DOCK" 'right: true' "Dock unexpectedly spans the right edge"
require_text "$DOCK" 'bottom: 8' "Dock optical bottom margin drifted away from the screen edge"
require_text "$DOCK" 'implicitWidth: 720' "Dock no longer uses the stable preview carrier"
require_text "$DOCK" 'implicitHeight: 326' "Dock no longer uses the stable preview carrier"
require_text "$DOCK" 'restingDockWidth: Math.max(320, dockRow.implicitWidth + 46)' "resting Dock is not icon-count driven"
require_text "$DOCK" 'item: root.previewOpen || root.previewProgress > 0.02 ? materialBounds : dockShell' "Dock input is not bounded to visible material state"
require_text "$DOCK" 'exclusionMode: ExclusionMode.Ignore' "Dock reserves compositor space"
require_text "$DOCK" 'WlrLayershell.namespace: "maho-dock"' "Dock has no scoped layer namespace"
require_text "$DOCK" 'WlrLayershell.layer: WlrLayer.Top' "Dock is not on the fullscreen-safe Top layer"
echo PASS

echo "=== adaptive premium glass ==="
require_text "$THEME" 'semanticSurfaceElevated' "Shell theme does not expose Palette V2 semantic material"
require_text "$DOCK" 'theme.semanticSurfaceElevated' "Dock ignores Palette V2 elevated surface"
require_text "$DOCK" 'theme.semanticBackground' "Dock does not adapt to wallpaper-derived background"
require_text "$DOCK" 'brightBackdrop' "Dock does not densify its material for bright palettes"
require_text "$DOCK" 'smokedNeutral' "Dock has no neutral smoked-glass base"
require_text "$DOCK" 'stableAccent(theme.semanticAccent)' "Dock accent is not stabilized"
require_text "$DOCK" 'shellOuterRim' "Dock lost the outer optical rim"
require_text "$DOCK" 'shellInnerRim' "Dock lost layered rim depth"
require_text "$DOCK" 'shellSpecular' "Dock lost the optical top reflection"
require_text "$DOCK" 'shellReflection' "Dock lost the broad reflective layer"
require_text "$DOCK" 'shellWell' "Dock lost its under-glass icon plane"
require_text "$DOCK" 'id: dockHalo' "Dock lost its outer separation plane"
require_text "$DOCK" 'id: dockDepth' "Dock lost optical depth behind the glass body"
require_text "$DOCK" 'id: dockInnerWell' "Dock icons no longer sit in a nested glass well"
require_text "$DECORATIONS" 'match = { namespace = "maho-dock" }' "Dock compositor blur is not namespace scoped"
require_text "$DECORATIONS" 'blur = true' "Dock compositor blur is missing"
require_text "$DECORATIONS" 'xray = false' "Dock blur does not respond to the real background stack"
reject_text "$DOCK" '#ff0000' "Dock hardcodes target-wallpaper red"
reject_text "$DOCK" '#ff' "Dock contains a hardcoded bright wallpaper color"
echo PASS

echo "=== coordinated motion and hover intent ==="
require_text "$DOCK" 'property real previewProgress: previewOpen ? 1 : 0' "preview reveal has no single material progress authority"
require_text "$DOCK" 'duration: 360' "preview material transition lost the deliberate reveal duration"
require_text "$DOCK" 'id: hoverIntent' "Dock has no hover-intent timer"
require_text "$DOCK" 'interval: 620' "window previews reveal too eagerly or too slowly"
require_text "$DOCK" 'previewHeight * root.previewProgress' "preview surface does not grow upward from the shelf"
require_text "$DOCK" 'previewDismiss' "preview has no graceful pointer-leave dismissal"
require_text "$DOCK" 'duration: 220' "icon hover motion is no longer calm"
require_text "$DOCK" 'id: hoverLens' "Dock has no shared sliding hover material"
require_text "$DOCK" 'Behavior on x {' "shared hover material does not travel smoothly"
reject_text "$DOCK" 'SpringAnimation' "Dock reintroduced bouncy motion"
echo PASS

echo "=== occlusion-aware retreat ==="
require_text "$DOCK" 'activeWindowOccupiesDock' "Dock does not detect real active-window occupation"
require_text "$DOCK" 'activeIpc.floating === false' "Dock does not distinguish tiled clients from small floating dialogs"
require_text "$DOCK" 'property real dockRevealProgress: retreatRequested ? 0 : 1' "Dock retreat has no single progress authority"
require_text "$DOCK" 'retractedHeight: 14' "Dock retreat is not a low-profile reveal shelf"
require_text "$DOCK" 'retractedWidth: 108' "Dock retreat affordance is not bounded"
require_text "$DOCK" 'id: retreatCue' "retracted Dock has no deliberate reveal affordance"
require_text "$DOCK" 'dockSurfaceHover.hovered' "Dock does not reveal from intentional pointer approach"
reject_text "$DOCK" 'Exclusive' "Dock retreat accidentally reserves workspace geometry"
echo PASS

echo "=== native window preview ==="
require_text "$PREVIEW" 'ScreencopyView {' "Dock preview does not use native screencopy"
require_text "$PREVIEW" 'top.handle || top.wayland || null' "Dock preview does not prefer the exported Hyprland toplevel handle"
require_text "$PREVIEW" 'live: root.active && captureSource !== null' "Dock preview stream is not demand-driven"
require_text "$PREVIEW" 'visible: !capture.hasContent' "Dock preview has no readiness fallback"
require_text "$PREVIEW" 'Preview unavailable' "failed native capture still renders as an unexplained blank frame"
require_text "$PREVIEW" 'paintCursor: false' "Dock window preview paints the pointer"
require_text "$DOCK" 'previewItem.windows.slice(0, 3)' "Dock preview does not use the selected app window group"
require_text "$DOCK" 'MahoDockPreviewCard {' "Dock does not render native window cards"
require_text "$DOCK" 'New Window' "preview panel lost the bounded new-window action"
reject_text "$PREVIEW" 'grabWindow' "Dock uses external screenshot machinery"
reject_text "$PREVIEW" 'grim' "Dock preview depends on external screenshot tooling"
echo PASS

echo "=== shared application identity ==="
require_text "$LAUNCHER_BACKEND" 'from maho_app_model import (' "Launcher does not use the shared Maho app model"
require_text "$APP_MODEL" '"startupWmClass"' "shared app model does not expose StartupWMClass"
require_text "$APP_MODEL" '"aliases"' "shared app model does not publish canonical aliases"
require_text "$MODEL" 'root.aliasToId[normalized]' "Dock does not match windows through canonical aliases"
require_text "$MODEL" 'clean(ipc.class)' "Dock does not consider Hyprland class"
require_text "$MODEL" 'clean(ipc.initialClass)' "Dock does not consider Hyprland initialClass"
require_text "$MODEL" 'toplevel.wayland.appId' "Dock does not consider Wayland appId"
require_text "$MODEL" 'const runningIds = Object.keys(grouped).filter(function(id) { return !represented[id] })' "pinned/running apps can duplicate"
python3 - "$MODEL" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
start = text.index("function identityForToplevel")
end = text.index("function windowRecord", start)
identity = text[start:end]
if ".title" in identity or "title)" in identity:
    raise SystemExit("FAIL: Dock matches application identity using window title")
PY
echo PASS

echo "=== event-driven Hyprland session model ==="
require_text "$MODEL" 'Hyprland.toplevels.values' "Dock does not consume Quickshell Hyprland toplevels"
require_text "$MODEL" 'function onRawEvent(event)' "Dock is not driven by Hyprland socket events"
require_text "$MODEL" 'Hyprland.refreshToplevels()' "Dock cannot refresh authoritative window metadata"
require_text "$MODEL" 'targetWorkspace.activate()' "Dock does not switch to the target workspace"
require_text "$MODEL" 'Hyprland.dispatch("focuswindow address:" + address)' "Dock does not focus the exact Hyprland window"
require_text "$MODEL" 'mruByAddress' "Dock has no MRU window ordering"
reject_text "$MODEL" 'repeat: true' "Dock introduced a repeating polling timer"
echo PASS

echo "=== versioned pin persistence ==="
require_text "$STATE" 'Quickshell.statePath("maho-dock.json")' "Dock pins do not use Maho state storage"
require_text "$STATE" 'property int version: 1' "Dock persisted state is not versioned"
require_text "$STATE" 'atomicWrites: true' "Dock state writes are not atomic"
require_text "$STATE" 'function sanitize(value)' "Dock does not sanitize persisted pin state"
require_text "$STATE" 'function movePin(fromIndex, toIndex)' "Dock order cannot be persisted/reordered later"
require_text "$MODEL" 'root.dockState.seedPins(output)' "first-run pins are not resolved to persisted real desktop IDs"
echo PASS

echo "=== responsibility and safety boundary ==="
for file in "$DOCK" "$PREVIEW" "$MODEL" "$STATE" "$RUNTIME"; do
    reject_text "$file" 'wifi' "Dock absorbed Wi-Fi responsibility"
    reject_text "$file" 'bluetooth' "Dock absorbed Bluetooth responsibility"
    reject_text "$file" 'battery' "Dock absorbed battery responsibility"
    reject_text "$file" 'brightness' "Dock absorbed brightness responsibility"
    reject_text "$file" 'volume' "Dock absorbed volume responsibility"
    reject_text "$file" 'notification' "Dock absorbed notification responsibility"
    reject_text "$file" 'weather' "Dock absorbed weather responsibility"
    reject_text "$file" 'clipboard' "Dock absorbed clipboard responsibility"
    reject_text "$file" 'pkill' "Dock contains broad name-based killing"
done
require_text "$DOCK" 'acceptedButtons: Qt.LeftButton | Qt.MiddleButton' "Dock primary/middle click contract missing"
require_text "$MODEL" 'Quickshell.execDetached(["python3", root.appModelPath, "launch-app", id])' "Dock launch does not use trusted XDG app identity"
echo PASS

echo "ALL MAHO DOCK M1.7 CONTRACTS PASS"
