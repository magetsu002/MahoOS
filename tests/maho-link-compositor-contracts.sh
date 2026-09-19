#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_QML="$ROOT/config/quickshell/maho-link/shell.qml"
BACKDROP="$ROOT/config/quickshell/maho-link/LinkBackdrop.qml"
LINK_VIEW="$ROOT/config/quickshell/maho-link/MahoLink.qml"
DECORATIONS="$ROOT/config/hypr/maho/appearance/decorations.lua"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require() {
    local file="$1" text="$2" message="$3"
    grep -Fq -- "$text" "$file" || fail "$message"
}

reject() {
    local file="$1" text="$2" message="$3"
    if grep -Fq -- "$text" "$file"; then
        fail "$message"
    fi
}

for file in "$SHELL_QML" "$BACKDROP" "$LINK_VIEW" "$DECORATIONS"; do
    [ -r "$file" ] || fail "missing file: $file"
done

echo '=== dedicated Link blur plane ==='
require "$SHELL_QML" 'shown: root.backdropVisible' \
    'Link blur carrier has no fade state'
require "$SHELL_QML" 'property bool backdropActive: true' \
    'Link blur carrier is not committed before foreground reveal'
require "$SHELL_QML" 'backdropActive = true' \
    'Link reopen path does not restore blur carrier'

require "$BACKDROP" 'WlrLayershell.namespace: "maho-link-backdrop"' \
    'Link backdrop namespace missing'
require "$BACKDROP" 'WlrLayershell.layer: WlrLayer.Top' \
    'Link blur carrier is not below Overlay foreground'
require "$BACKDROP" 'mask: Region {}' \
    'Link blur carrier can intercept input'
require "$BACKDROP" 'Qt.rgba(0, 0, 0, 0.008)' \
    'Link blur carrier alpha is not stable'
require "$BACKDROP" 'property bool shown: false' \
    'Link backdrop has no explicit fade visibility state'
require "$BACKDROP" 'duration: root.shown ? 68 : 0' \
    'Link backdrop still animates blur during dismissal'

echo PASS

echo '=== Hyprland blur ownership ==='
require "$DECORATIONS" 'namespace = "maho-link-backdrop"' \
    'Hyprland Link blur is not scoped to dedicated backdrop'
require "$DECORATIONS" 'ignore_alpha = 0.001' \
    'Link blur threshold can toggle during foreground alpha animation'
reject "$DECORATIONS" 'namespace = "maho-link",' \
    'interactive Link Overlay still owns compositor blur'
echo PASS

echo '=== foreground motion preserved ==='
require "$SHELL_QML" 'WlrLayershell.namespace: "maho-link"' \
    'interactive Link namespace changed unexpectedly'
require "$LINK_VIEW" 'scale: shown ? 1 : (closing ? 1 : 0.988)' \
    'Link no longer has a distinct open-only scale intro'
require "$LINK_VIEW" 'y: root.shown ? 0 : (root.closing ? 0 : -8)' \
    'Link no longer has a distinct open-only lift intro'
require "$LINK_VIEW" 'Behavior on opacity' \
    'accepted Link opacity motion was removed'
echo PASS
require "$LINK_VIEW" 'property bool closing: false' \
    'Link cannot distinguish intro motion from close-only fade'
require "$SHELL_QML" 'backdropVisible = false' \
    'Link close does not begin compositor blur fade immediately'
require "$SHELL_QML" 'backdropActive = false' \
    'Link close does not unmap compositor blur immediately'
require "$SHELL_QML" 'root.backdropActive = false' \
    'Link blur carrier does not unmap after the close fade'
require "$SHELL_QML" 'visible: root.presented' \
    'interactive full-screen Link overlay remains mapped while warm-hidden'
require "$SHELL_QML" 'namespace: "maho-link-keepalive"' \
    'Link warm residency still depends on a full-screen overlay'
require "$SHELL_QML" 'implicitWidth: 1' \
    'Link keepalive is not bounded to a tiny compositor surface'

echo '=== Bluetooth final-geometry reveal ==='
require "$LINK_VIEW" 'Behavior on height { enabled: root.shown;' \
    'hidden Link geometry still animates and requires an artificial reveal delay'
require "$SHELL_QML" 'Qt.callLater(root.revealSurfaceWhenReady)' \
    'Bluetooth does not reveal on the next event turn after hidden geometry snaps'
reject "$SHELL_QML" 'bluetoothRevealTimer' \
    'Bluetooth still carries the old artificial geometry wait'
reject "$SHELL_QML" 'bluetoothGeometryReady' \
    'Bluetooth still carries the old geometry gate'
echo PASS

echo '=== authoritative Escape dismissal ==='
require "$SHELL_QML" 'sequence: "Escape"' \
    'Link has no overlay-level Escape shortcut'
require "$SHELL_QML" 'context: Qt.ApplicationShortcut' \
    'Escape still depends on whichever child owns focus'
require "$SHELL_QML" 'enabled: root.overlayOpen' \
    'Escape shortcut is not bounded to the open overlay'
require "$SHELL_QML" 'onActivated: root.closeOverlay()' \
    'Escape shortcut does not close Link'
require "$SHELL_QML" 'WlrLayershell.keyboardFocus: root.overlayOpen' \
    'Link does not explicitly own keyboard focus while open'
require "$SHELL_QML" '? WlrKeyboardFocus.Exclusive' \
    'Link is not exclusive keyboard focus while presented'
require "$SHELL_QML" ': WlrKeyboardFocus.None' \
    'Link does not release keyboard focus immediately on close'
echo PASS

echo 'ALL MAHO LINK COMPOSITOR CONTRACTS PASS'
