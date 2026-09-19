#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_DIR="$ROOT/config/quickshell/maho-shell"
RUNTIME="$ROOT/bin/maho-shell"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_file() {
    local file="$1"
    [ -r "$SHELL_DIR/$file" ] || fail "missing shell component: $file"
}

require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$SHELL_DIR/$file" || fail "$message"
}

require_runtime_text() {
    local needle="$1" message="$2"
    grep -Fq -- "$needle" "$RUNTIME" || fail "$message"
}

echo "=== packaged components ==="
for file in \
    shell.qml \
    MahoTheme.qml \
    Audio.qml \
    Brightness.qml \
    Battery.qml \
    Media.qml \
    SystemState.qml \
    DockState.qml \
    DockReservation.qml \
    MahoCard.qml \
    SliderCard.qml \
    WorkspaceRail.qml \
    EdgeBar.qml \
    SideEdgeBar.qml \
    NotifyStatus.qml \
    ControlCenter.qml \
    state.py
 do
    require_file "$file"
 done
[ ! -e "$SHELL_DIR/CollapsedIsland.qml" ] || fail "legacy CollapsedIsland.qml returned"
[ ! -e "$SHELL_DIR/SideCollapsedIsland.qml" ] || fail "legacy SideCollapsedIsland.qml returned"
echo "PASS"

echo "=== narrow Notify bridge contract ==="
require_text NotifyStatus.qml 'Quickshell.env("XDG_RUNTIME_DIR")' "Notify status is not user-runtime scoped"
require_text NotifyStatus.qml '/maho/notify-status.json' "Notify metadata sidecar path missing"
require_text NotifyStatus.qml 'watchChanges: true' "Notify metadata is not observed reactively"
require_text NotifyStatus.qml 'statusFile.loaded' "missing Notify metadata does not fall back safely"
require_text NotifyStatus.qml 'data.version === 1' "malformed/unknown Notify metadata is not rejected"
require_text NotifyStatus.qml 'readonly property int processId:' "Notify live-process routing metadata missing"
require_text ControlCenter.qml 'property var notifyStatus' "expanded control center lacks Notify status"
require_text ControlCenter.qml 'text: "Notifications"' "expanded control center Notify entry missing"
require_text ControlCenter.qml 'notifyStatus.unreadCount' "expanded Notify entry unread state missing"
require_text ControlCenter.qml 'notifyStatus.dndEnabled' "expanded Notify entry DND state missing"
require_text ControlCenter.qml 'center.notificationsRequested()' "expanded Notify entry cannot request center open"
require_text shell.qml 'function openNotificationCenter()' "Maho Edge center-open bridge missing"
require_text shell.qml '"quickshell", "ipc", "--pid"' "live Notify IPC path missing"
require_text shell.qml 'String(notifyBridge.processId)' "live Notify PID is not routed to IPC"
require_text shell.qml '/.local/bin/maho-notify' "Maho Edge does not use the managed Notify runtime"
require_text shell.qml 'onNotificationsRequested: root.openNotificationCenter()' "Notify open request is not routed"
if grep -Fq 'NotifyIndicator' "$SHELL_DIR/EdgeBar.qml" "$SHELL_DIR/SideEdgeBar.qml" \
    || grep -Fq 'notifyStatus' "$SHELL_DIR/EdgeBar.qml" "$SHELL_DIR/SideEdgeBar.qml"; then
    fail "notification state leaked into the collapsed Maho Edge"
fi
if grep -RnsE 'state\.json|HistoryModel|HistoryRow|NotificationCenter|NotificationModel|NotificationCard' \
    "$SHELL_DIR/NotifyStatus.qml" "$SHELL_DIR/ControlCenter.qml"; then
    fail "Maho Edge bridge owns or imports notification history/UI"
fi
if grep -RnsEi '\b(body|summary|appName|title)\b' \
    "$SHELL_DIR/NotifyStatus.qml"; then
    fail "notification content field exposed to Maho Edge"
fi
if grep -Fq 'Timer {' "$SHELL_DIR/NotifyStatus.qml" || grep -Fq 'Process {' "$SHELL_DIR/NotifyStatus.qml"; then
    fail "Notify status bridge uses polling or subprocess refresh"
fi
echo "PASS"

echo "=== Super+Space Maho Edge contract ==="
require_text shell.qml 'target: "edge"' "Maho Edge IPC target missing"
require_text shell.qml 'function open(): bool' "Maho Edge IPC open method missing"
require_text shell.qml 'root.openPanel()' "Maho Edge IPC does not route to native openPanel"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"
grep -Fq 'mainMod .. " + SPACE"' "$BINDS" || fail "SUPER+SPACE bind missing"
grep -Fq 'call edge open' "$BINDS" || fail "SUPER+SPACE does not open Maho Edge"
if grep -F 'mainMod .. " + SPACE"' "$BINDS" | grep -Fq 'rofi'; then
    fail "SUPER+SPACE still launches Rofi"
fi
echo "PASS"

echo "=== dynamic palette contract ==="
require_text MahoTheme.qml '/.cache/maho/theme/active.json' "theme does not read Maho active palette"
require_text MahoTheme.qml 'watchChanges: true' "theme does not watch palette changes"
require_text MahoTheme.qml 'property color primary:' "theme does not expose primary color"
require_text MahoTheme.qml 'property color surfaceHigh:' "theme does not expose surface hierarchy"
echo "PASS"

echo "=== QML scope import contract ==="
require_text Battery.qml 'import Quickshell' "Battery.qml uses Scope without importing Quickshell"
require_text Media.qml 'import Quickshell' "Media.qml uses Scope without importing Quickshell"
require_text DockState.qml 'import Quickshell' "DockState.qml uses Scope without importing Quickshell"
require_text DockState.qml 'import Quickshell.Io' "DockState.qml does not import Quickshell.Io"
require_text DockReservation.qml 'import Quickshell' "DockReservation.qml does not import Quickshell"
echo "PASS"

echo "=== native live interaction contract ==="
require_text Audio.qml 'import Quickshell.Services.Pipewire' "audio is not PipeWire-native"
require_text Audio.qml 'function setVolume(percent)' "audio volume mutation missing"
require_text Audio.qml 'function toggleMute()' "audio mute mutation missing"
require_text EdgeBar.qml 'onWheel: function(wheel)' "Maho Edge wheel interaction missing"
require_text EdgeBar.qml 'edge.audio.setVolume' "Maho Edge wheel does not drive audio service"
require_text EdgeBar.qml 'edge.audio.toggleMute()' "Maho Edge middle-click mute missing"
require_text EdgeBar.qml 'edge.openRequested()' "Maho Edge does not open control center"
require_text SideEdgeBar.qml 'onWheel: function(wheel)' "side Maho Edge wheel interaction missing"
require_text SideEdgeBar.qml 'edge.audio.toggleMute()' "side Maho Edge middle-click mute missing"
require_text SideEdgeBar.qml 'edge.openRequested()' "side Maho Edge does not open control center"
echo "PASS"

echo "=== native battery contract ==="
require_text Battery.qml 'import Quickshell.Services.UPower' "battery is not UPower-native"
require_text Battery.qml 'UPower.displayDevice' "battery does not use the UPower display device"
require_text Battery.qml 'device.percentage * 100' "UPower normalized percentage is not scaled to 0..100"
require_text Battery.qml 'UPowerDeviceState.Charging' "battery charging state binding missing"
require_text shell.qml 'Battery { id: battery }' "shell does not instantiate native battery service"
require_text shell.qml 'battery: battery' "shell does not pass native battery state to views"
if grep -Fq '/sys/class/power_supply' "$SHELL_DIR/state.py"; then
    fail "ambient state probe still polls battery sysfs"
fi
echo "PASS"

echo "=== native media contract ==="
require_text Media.qml 'import Quickshell.Services.Mpris' "media is not MPRIS-native"
require_text Media.qml 'Mpris.players.values' "media does not use Quickshell MPRIS player model"
require_text Media.qml 'function previous()' "native media previous action missing"
require_text Media.qml 'function toggle()' "native media play/pause action missing"
require_text Media.qml 'function next()' "native media next action missing"
require_text shell.qml 'Media { id: media }' "shell does not instantiate native media service"
require_text shell.qml 'onMediaToggleRequested: media.toggle()' "control center does not route play/pause to native media"
if grep -Fq 'playerctl' "$SHELL_DIR/state.py"; then
    fail "ambient state probe still polls media through playerctl"
fi
echo "PASS"

echo "=== workspace travel contract ==="
require_text shell.qml 'import Quickshell.Hyprland' "shell does not import native Hyprland service"
require_text shell.qml 'Hyprland.focusedWorkspace' "shell does not use native focused workspace state"
require_text shell.qml 'function onRawEvent(event)' "shell does not consume raw Hyprland events"
require_text shell.qml 'event.name !== "workspacev2"' "workspacev2 is not the workspace animation authority"
require_text shell.qml 'event.parse(2)' "workspacev2 payload is not parsed as id/name"
require_text shell.qml 'workspaceEventSerial += 1' "workspace changes do not receive a unique event serial"
require_text shell.qml 'workspaceTravel = true' "workspace travel does not expand the active marker"
require_text shell.qml 'id: workspaceTravelTimer' "workspace travel has no bounded pill lifetime"
require_text shell.qml 'workspaceTravel = false' "workspace marker never settles back to a dot while feedback remains visible"
require_text WorkspaceRail.qml 'readonly property int slotCount: 5' "workspace rail is not fixed to five slots"
require_text WorkspaceRail.qml 'readonly property int activeSlot:' "workspace rail does not map workspace number to a stable slot"
require_text WorkspaceRail.qml 'id: activeMarker' "workspace rail lacks one movable active marker"
require_text WorkspaceRail.qml 'property bool switching: false' "workspace rail lacks transient dot-to-pill state"
require_text WorkspaceRail.qml '(rail.switching ? rail.markerLength : rail.dotSize)' "workspace marker does not collapse to a dot at rest"
require_text EdgeBar.qml 'switching: edge.workspaceTravel' "horizontal Edge does not drive transient workspace marker shape"
require_text SideEdgeBar.qml 'switching: edge.workspaceTravel' "side Edge does not drive transient workspace marker shape"
require_text WorkspaceRail.qml 'rail.activeSlot * rail.step' "active workspace marker is not spatially positioned by slot"
require_text WorkspaceRail.qml 'Behavior on x' "horizontal workspace marker does not animate across slots"
require_text WorkspaceRail.qml 'Behavior on y' "vertical workspace marker does not animate across slots"
require_text EdgeBar.qml 'WorkspaceRail {' "horizontal Maho Edge does not use the shared workspace rail"
require_text SideEdgeBar.qml 'WorkspaceRail {' "side Maho Edge does not use the shared workspace rail"
require_text SideEdgeBar.qml 'vertical: true' "side workspace rail is not vertical"
if grep -RnsF 'workspacePulseAnimation' "$SHELL_DIR/EdgeBar.qml" "$SHELL_DIR/SideEdgeBar.qml"; then
    fail "legacy whole-workspace pulse animation returned"
fi
echo "PASS"

echo "=== persistent edge docking contract ==="
require_text DockState.qml 'Quickshell.statePath("dock.json")' "dock state is not stored in Quickshell state storage"
require_text DockState.qml 'JsonAdapter {' "dock state is not JSON-backed"
require_text DockState.qml 'property string edge: "top"' "dock state lacks a safe top default"
require_text DockState.qml 'property real position: 0.5' "dock state lacks along-edge position"
require_text DockState.qml 'function setDock(nextEdge, nextPosition)' "dock state mutation API missing"
require_text shell.qml 'DockState { id: dock }' "shell does not instantiate persistent dock state"
require_text shell.qml 'function nearestEdge(centerX, centerY)' "nearest-edge snap policy missing"
require_text shell.qml 'function edgePosition(edge, centerX, centerY)' "along-edge snap position missing"
require_text shell.qml 'dock.setDock(edge, position)' "drag release does not persist snapped dock state"
require_text shell.qml 'exclusionMode: ExclusionMode.Ignore' "full-screen drag layer should not reserve the desktop"
require_text shell.qml 'mask: Region { item: edgeSurface }' "full-screen drag layer is not input-masked to Maho Edge"
require_text shell.qml 'dock.edge === "left" || dock.edge === "right"' "vertical dock orientation missing"
require_text shell.qml 'dock.edge === "bottom" ? 180' "bottom silhouette orientation missing"
require_text shell.qml 'dock.edge === "left" ? -90' "left silhouette orientation missing"
require_text shell.qml 'dock.edge === "right" ? 90' "right silhouette orientation missing"
echo "PASS"

echo "=== runtime-proven drag freeze contract ==="
require_text shell.qml 'DragHandler {' "Maho Edge drag handler missing"
require_text shell.qml 'id: dockDrag' "runtime-proven drag handler id changed"
require_text shell.qml 'target: null' "dock drag must not bypass bounded snap geometry"
require_text shell.qml 'acceptedButtons: Qt.LeftButton' "dock drag left-button contract changed"
require_text shell.qml 'dragThreshold: 8' "runtime-proven drag threshold changed"
require_text shell.qml 'activeTranslation.x' "dock drag does not follow pointer translation"
if grep -Fq 'id: dockInput' "$SHELL_DIR/shell.qml"; then
    fail "experimental full-surface MouseArea drag path returned"
fi
echo "PASS"

echo "=== compositor reservation contract ==="
require_text shell.qml 'DockReservation {' "Maho Edge does not instantiate compositor reservation"
require_text shell.qml 'screen: panel.screen' "reservation is not tied to the visible Edge screen"
require_text shell.qml 'breathingRoom: 8' "Maho Edge breathing room changed unexpectedly"
require_text DockReservation.qml 'exclusiveZone: reservedThickness' "reservation does not own an exclusive zone"
require_text DockReservation.qml 'horizontalBarThickness: 40' "horizontal reservation lost collapsed Edge thickness"
require_text DockReservation.qml 'verticalBarThickness: 46' "vertical reservation lost collapsed Edge thickness"
require_text DockReservation.qml 'mask: Region {}' "reservation can intercept desktop input"
require_text DockReservation.qml 'aboveWindows: false' "reservation should not render as a top overlay"
require_text DockReservation.qml 'dock.edge === "top" || vertical' "reservation does not follow dock orientation"
[ "$(sha256sum "$SHELL_DIR/DockReservation.qml" | awk '{print $1}')" = \
    "2819e566fc3d40c634ca05007c6b49bae4aab30d4b504316f4b27d47e2e98475" ] || \
    fail "DockReservation changed from the accepted frozen implementation"
require_text shell.qml '? 250' "accepted Edge transient dimensions changed"
require_text shell.qml ': (root.workspaceFlash ? 205 : (edgeView.hovered ? 190 : 176))' "horizontal Edge geometry changed"
require_text shell.qml ': (root.workspaceFlash ? 205 : (sideEdgeView.hovered ? 202 : 190))' "vertical Edge geometry changed"
echo "PASS"

echo "=== staged close contract ==="
require_text shell.qml 'property bool closing: false' "shell close state missing"
require_text shell.qml 'property bool controlVisible: false' "control visibility state missing"
require_text shell.qml 'closeMorphTimer.restart()' "close does not stage content fade before shape morph"
require_text shell.qml 'id: closeSecondaryTimer' "close does not stage primary and secondary geometry folds"
require_text shell.qml 'readonly property bool wideBody: root.expanded || root.closing' "closing no longer preserves expanded geometry during primary fold"
require_text shell.qml 'interval: root.verticalDock ? 255 : 185' "close choreography is not orientation-aware"
require_text shell.qml 'opacity: root.controlVisible ? 1 : 0' "control center fade contract missing"
if grep -Fq 'closeSurfaceTimer' "$SHELL_DIR/shell.qml"; then
    fail "delayed layer-surface shrink artifact path returned"
fi
echo "PASS"

echo "=== slider uniqueness and hitbox contract ==="
VOLUME_COUNT="$(grep -Fc 'titleText: "Volume"' "$SHELL_DIR/ControlCenter.qml")"
BRIGHTNESS_COUNT="$(grep -Fc 'titleText: "Brightness"' "$SHELL_DIR/ControlCenter.qml")"
[ "$VOLUME_COUNT" -eq 1 ] || fail "expected one Volume slider, found $VOLUME_COUNT"
[ "$BRIGHTNESS_COUNT" -eq 1 ] || fail "expected one Brightness slider, found $BRIGHTNESS_COUNT"
require_text SliderCard.qml 'property int value: 0' "slider service value contract missing"
require_text SliderCard.qml 'property real previewValue: value' "slider local drag preview missing"
require_text SliderCard.qml 'readonly property real displayedValue:' "slider rendered-value arbitration missing"
require_text SliderCard.qml 'onValueChanged:' "slider does not follow service-side changes"
require_text SliderCard.qml 'dragArea.dragging ? previewValue : value' "slider does not return to live service value outside drag"
require_text SliderCard.qml 'height: 28' "slider interaction lane regressed to tiny visual track"
echo "PASS"

echo "=== explicit action feedback contract ==="
require_text shell.qml 'function requestLock()' "lock action staging missing"
require_text shell.qml "hyprlock is not installed" "lock action can fail silently"
require_text shell.qml 'function requestCapture()' "capture action staging missing"
require_text shell.qml "No screenshot backend is installed" "capture action can fail silently"
echo "PASS"

echo "=== runtime diagnostics contract ==="
require_runtime_text 'doctor)' "maho-shell doctor command missing"
require_runtime_text 'status --json' "machine-readable shell status missing"
require_runtime_text 'logs [LINES]' "bounded runtime log command missing"
require_runtime_text 'if [ "$lines" -lt 1 ] || [ "$lines" -gt 500 ]' "runtime log bound missing"
require_runtime_text 'shell_count()' "singleton diagnostics missing"
require_runtime_text 'nohup bash "$0" run' "fallback start still executes immutable runtime source directly"
require_runtime_text 'bash "$0" stop' "reload stop still executes immutable runtime source directly"
require_runtime_text 'bash "$0" start' "reload start still executes immutable runtime source directly"
if grep -Fiq -- 'waybar' "$RUNTIME"; then
    fail "Maho Shell runtime still contains legacy Waybar behavior"
fi
require_runtime_text 'python -m json.tool "$PALETTE"' "palette diagnostics missing"
require_runtime_text 'print_capability brightnessctl' "brightness capability diagnostics missing"
require_runtime_text 'print_capability nmcli' "network capability diagnostics missing"
echo "PASS"

echo "=== known QML footgun contract ==="
if grep -RnsE '^[[:space:]]*letterSpacing[[:space:]]*:' "$SHELL_DIR" --include='*.qml'; then
    fail "top-level letterSpacing property found; use font.letterSpacing"
fi
echo "PASS"

echo "ALL MAHO SHELL CONTRACTS PASS"
