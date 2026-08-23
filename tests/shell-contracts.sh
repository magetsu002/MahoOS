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
    Media.qml \
    SystemState.qml \
    MahoCard.qml \
    SliderCard.qml \
    CollapsedIsland.qml \
    ControlCenter.qml \
    state.py
 do
    require_file "$file"
 done
echo "PASS"

echo "=== dynamic palette contract ==="
require_text MahoTheme.qml '/.cache/maho/theme/active.json' "theme does not read Maho active palette"
require_text MahoTheme.qml 'watchChanges: true' "theme does not watch palette changes"
require_text MahoTheme.qml 'property color primary:' "theme does not expose primary color"
require_text MahoTheme.qml 'property color surfaceHigh:' "theme does not expose surface hierarchy"
echo "PASS"

echo "=== native live interaction contract ==="
require_text Audio.qml 'import Quickshell.Services.Pipewire' "audio is not PipeWire-native"
require_text Audio.qml 'function setVolume(percent)' "audio volume mutation missing"
require_text Audio.qml 'function toggleMute()' "audio mute mutation missing"
require_text CollapsedIsland.qml 'onWheel: function(wheel)' "collapsed island wheel interaction missing"
require_text CollapsedIsland.qml 'collapsed.audio.setVolume' "collapsed island wheel does not drive audio service"
require_text CollapsedIsland.qml 'collapsed.audio.toggleMute()' "collapsed island middle-click mute missing"
require_text CollapsedIsland.qml 'collapsed.openRequested()' "collapsed island does not open control center"
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

echo "=== workspace responsiveness contract ==="
require_text shell.qml 'import Quickshell.Hyprland' "shell does not import native Hyprland service"
require_text shell.qml 'Hyprland.focusedWorkspace' "shell does not use native focused workspace state"
require_text shell.qml 'onFocusedWorkspaceChanged()' "shell does not react to workspace events"
echo "PASS"

echo "=== staged close contract ==="
require_text shell.qml 'property bool closing: false' "shell close state missing"
require_text shell.qml 'property bool controlVisible: false' "control visibility state missing"
require_text shell.qml 'closeMorphTimer.restart()' "close does not stage content fade before shape morph"
require_text shell.qml 'opacity: root.controlVisible ? 1 : 0' "control center fade contract missing"
echo "PASS"

echo "=== slider uniqueness contract ==="
VOLUME_COUNT="$(grep -Fc 'titleText: "Volume"' "$SHELL_DIR/ControlCenter.qml")"
BRIGHTNESS_COUNT="$(grep -Fc 'titleText: "Brightness"' "$SHELL_DIR/ControlCenter.qml")"
[ "$VOLUME_COUNT" -eq 1 ] || fail "expected one Volume slider, found $VOLUME_COUNT"
[ "$BRIGHTNESS_COUNT" -eq 1 ] || fail "expected one Brightness slider, found $BRIGHTNESS_COUNT"
require_text SliderCard.qml 'property int value: 0' "slider service value contract missing"
require_text SliderCard.qml 'property real previewValue: value' "slider local drag preview missing"
require_text SliderCard.qml 'readonly property real displayedValue:' "slider rendered-value arbitration missing"
require_text SliderCard.qml 'onValueChanged:' "slider does not follow service-side changes"
require_text SliderCard.qml 'dragArea.dragging ? previewValue : value' "slider does not return to live service value outside drag"
echo "PASS"

echo "=== runtime diagnostics contract ==="
require_runtime_text 'doctor)' "maho-shell doctor command missing"
require_runtime_text 'status --json' "machine-readable shell status missing"
require_runtime_text 'logs [LINES]' "bounded runtime log command missing"
require_runtime_text 'if [ "$lines" -lt 1 ] || [ "$lines" -gt 500 ]' "runtime log bound missing"
require_runtime_text 'shell_count()' "singleton diagnostics missing"
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
