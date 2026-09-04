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

echo "=== desktop-only resting policy ==="
require_text "$DOCK_ENTRY" 'import Quickshell.Hyprland' "Dock entrypoint cannot observe active application windows"
require_text "$DOCK_ENTRY" 'const top = Hyprland.activeToplevel' "Dock resting policy is not driven by the active toplevel"
require_text "$DOCK_ENTRY" 'const hasActiveAppWindow = Boolean(top && top.activated)' "Dock does not distinguish an empty desktop from an active app window"
require_text "$DOCK_ENTRY" '&& !dock.pointerInsideMaterial' "intentional pointer approach cannot reveal a retracted Dock"
require_text "$DOCK_ENTRY" '&& !dock.previewOpen' "open previews cannot keep the Dock revealed"
require_text "$DOCK_ENTRY" 'return shouldRetreat ? 0 : 1' "Dock does not retract for every active app window"
echo PASS

echo "=== bounded stable carrier ==="
require_text "$DOCK" 'bottom: true' "Dock is not bottom anchored"
reject_text "$DOCK" 'top: true' "Dock unexpectedly spans the top edge"
reject_text "$DOCK" 'left: true' "Dock unexpectedly spans the left edge"
reject_text "$DOCK" 'right: true' "Dock unexpectedly spans the right edge"
require_text "$DOCK" 'bottom: 2' "Dock optical bottom margin drifted away from the screen edge"
require_text "$DOCK" 'implicitWidth: 720' "Dock no longer uses the stable preview carrier"
require_text "$DOCK" 'implicitHeight: 438' "Dock no longer has enough carrier height for adaptive previews"
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
require_text "$DOCK" 'id: dockReflectionField' "Dock lost the accepted continuous reflection field"
require_text "$DOCK" 'id: previewReflectionField' "preview lost the accepted continuous reflection field"
require_text "$DECORATIONS" 'match = { namespace = "maho-dock" }' "Dock compositor blur is not namespace scoped"
require_text "$DECORATIONS" 'blur = true' "Dock compositor blur is missing"
require_text "$DECORATIONS" 'xray = false' "Dock blur ignores the real background stack"
reject_text "$DOCK" '#ff0000' "Dock hardcodes target-wallpaper red"
reject_text "$DOCK" 'experimentalRightGlint' "legacy white side-glint artifact returned"
echo PASS

echo "=== coordinated motion and deterministic hover preview ==="
require_text "$DOCK" 'property real previewProgress: previewOpen ? 1 : 0' "preview reveal has no single material progress authority"
require_text "$DOCK" 'interval: 620' "window preview hover intent drifted"
require_text "$DOCK" 'readonly property bool pointerInsideMaterial' "preview dismissal still relies on stale manual hover bookkeeping"
require_text "$DOCK" 'dockSurfaceHover.hovered || previewHover.hovered' "Dock and preview do not share one pointer-inside authority"
require_text "$DOCK" 'if (!root.pointerInsideMaterial)' "preview dismissal does not collapse after leaving the whole material"
require_text "$DOCK" 'id: hoverLens' "Dock has no shared sliding hover material"
reject_text "$DOCK" 'property bool dockHovering' "stale dockHovering bookkeeping can wedge the preview open"
reject_text "$DOCK" 'SpringAnimation' "Dock reintroduced bouncy motion"
reject_text "$MODEL" '"windowtitle"' "window-title churn can still rebuild hovered Dock delegates"
require_text "$PREVIEW" 'readonly property string liveWindowTitle:' "preview does not read mutable window title metadata live"
require_text "$PREVIEW" 'root.windowData.toplevel.title' "preview title is still tied to stale model snapshots"
require_text "$DOCK" 'property string hoverCandidateId:' "hover preview still stores disposable delegate objects"
reject_text "$DOCK" 'property var hoverCandidate:' "legacy delegate-object hover candidate returned"
require_text "$DOCK" 'function currentDockItemById(id)' "hover intent cannot resolve the current live Dock item"
require_text "$DOCK" 'root.currentDockItemById(root.hoverCandidateId)' "hover timer does not re-resolve identity at trigger time"
require_text "$DOCK" 'function dockItemUnderPointer()' "Dock cannot recover hover after stationary geometry/model changes"
require_text "$DOCK" 'id: appRepeater' "hover recovery cannot inspect current rendered app cells"
require_text "$DOCK" 'id: hoverWatchdog' "Dock lacks UI-only hover intent repair"
require_text "$DOCK" 'interval: 90' "hover repair cadence drifted"
require_text "$DOCK" 'onTriggered: root.syncHoverIntent()' "hover repair does not reconcile the actual pointer target"
echo PASS

echo "=== native adaptive window preview ==="
require_text "$PREVIEW" 'ScreencopyView {' "Dock preview does not use native screencopy"
require_text "$PREVIEW" 'top.handle || top.wayland || null' "Dock preview does not prefer an exported toplevel handle"
require_text "$PREVIEW" 'visible: !capture.hasContent' "Dock preview has no capture readiness fallback"
require_text "$PREVIEW" 'Preview unavailable' "capture failure still renders as unexplained blank content"
require_text "$DOCK" 'if (!previewItem || !previewItem.windows)' "Dock preview still relies on brittle Array.isArray gating"
require_text "$DOCK" 'windows.slice(0, 3)' "Dock preview does not bound selected app windows"
require_text "$DOCK" 'previewCount <= 1 ? 540' "single-window preview does not adapt its shell width"
require_text "$DOCK" 'previewCount === 2 ? 660' "two-window preview does not use balanced width"
require_text "$DOCK" 'previewCount <= 1 ? 414' "single-window preview is not promoted to a hero card"
require_text "$DOCK" 'id: previewStage' "preview cards have no dedicated layout stage"
require_text "$PREVIEW" 'property real cardWidth:' "preview card cannot accept adaptive width"
require_text "$PREVIEW" 'property real cardHeight:' "preview card cannot accept adaptive height"
require_text "$PREVIEW" 'width: cardWidth' "preview card width is not driven by adaptive layout"
require_text "$PREVIEW" 'height: cardHeight' "preview card height is not driven by adaptive layout"
require_text "$DOCK" 'MahoDockPreviewCard {' "Dock does not render window cards"
echo PASS

echo "=== exact window close controls ==="
require_text "$DOCK" 'id: previewCloseAction' "single-window preview has no shell-level close control"
require_text "$DOCK" 'root.previewCount === 1 && root.previewOpen' "single-window close control is not scoped correctly"
require_text "$DOCK" 'root.closeWindowRecord(root.previewWindows[0])' "single-window close control does not target the exact window"
require_text "$DOCK" 'showCloseButton: root.previewCount > 1' "multi-window cards do not expose per-window close controls"
require_text "$PREVIEW" 'property bool showCloseButton: true' "preview card cannot scope its close affordance"
require_text "$PREVIEW" 'function closeWindow()' "preview card has no exact close action"
require_text "$PREVIEW" 'const handle = top.handle || top.wayland || null' "preview close does not resolve the real Wayland toplevel"
require_text "$PREVIEW" 'handle.close()' "preview close does not issue a native toplevel close request"
require_text "$PREVIEW" 'enabled: !closeMouse.containsMouse' "close click can leak into normal preview activation"
reject_text "$PREVIEW" 'pkill' "preview close kills processes instead of closing the selected window"
reject_text "$PREVIEW" 'killactive' "preview close can kill the wrong active window"
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

echo "ALL MAHO DOCK TARGET CONTRACTS PASS"
