#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_QML="$ROOT/config/quickshell/maho-link/shell.qml"
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

for file in "$SHELL_QML" "$LINK_VIEW" "$DECORATIONS"; do
    [ -r "$file" ] || fail "missing file: $file"
done

echo '=== split catcher + blurred material architecture ==='
require "$SHELL_QML" 'WlrLayershell.namespace: "maho-link-catcher"'     'Link full-screen catcher does not have an isolated namespace'
require "$SHELL_QML" 'The catcher must stay below the foreground material'     'Link catcher/material pointer-order contract is missing'
require "$SHELL_QML" 'WlrLayershell.namespace: "maho-link"'     'Link material namespace changed unexpectedly'
require "$SHELL_QML" 'mask: Region { item: root.overlayOpen ? linkSurface : null }'     'Link material blur is not alpha/input bounded to the rounded card'
reject "$SHELL_QML" 'LinkBackdrop {'     'Link regressed to a separate compositor blur carrier'
reject "$SHELL_QML" 'maho-link-backdrop'     'Link still references the old backdrop blur namespace'
require "$DECORATIONS" 'name = "maho-link-material"'     'Link foreground blur rule is missing'
require "$DECORATIONS" 'match = { namespace = "maho-link" }'     'Link blur rule does not target the material namespace'
require "$DECORATIONS" 'ignore_alpha = 0.16'     'Link blur alpha mask drifted from the proven Notify material model'
require "$DECORATIONS" 'no_anim = true'     'Link compositor blur is participating in compositor animation'
reject "$DECORATIONS" 'namespace = "maho-link-catcher"'     'Link full-screen catcher must never be blurred'
[ ! -e "$ROOT/config/quickshell/maho-link/LinkBackdrop.qml" ]     || fail "obsolete LinkBackdrop.qml still exists"
[ ! -e "$ROOT/config/quickshell/maho-link/assets/material-noise.png" ]     || fail "obsolete Link dither texture still exists"
echo PASS

echo '=== fixed-geometry translucent material ==='
require "$LINK_VIEW" 'Behavior on opacity'     'Link lost its material fade'
require "$LINK_VIEW" 'enabled: !root.shown'     'Link opening can still animate a staged/wrong first frame'
require "$LINK_VIEW" 'duration: 26'     'Link close fade drifted from the bounded dismissal timing'
require "$SHELL_QML" 'if (!presented || !placementReady || linkSurface.shown)'     'Link reveal still depends on prematurely active catcher state'
require "$SHELL_QML" 'overlayOpen = true'     'Link synchronized reveal does not activate catcher with the material'
require "$SHELL_QML" 'Present Link as one compositor event'     'Link synchronized intro contract is missing'
reject "$LINK_VIEW" 'Behavior on scale'     'Link still animates glass geometry through subpixel scale'
reject "$LINK_VIEW" 'transform: Translate'     'Link still translates glass borders/highlights during intro'
require "$LINK_VIEW" 'theme.alpha(neutralGlass, 0.72)'     'Link glass fill drifted from the neutral glass target'
require "$LINK_VIEW" 'theme.alpha(theme.foreground, 0.105)'     'Link rim drifted from the shared material family'
require "$SHELL_QML" 'root.overlayOpen ? 0.075 : 0'     'Link catcher dim is not the intended subtle dark overlay'
require "$SHELL_QML" 'duration: root.overlayOpen ? 64 : 0'     'Link dim plane still fades after dismissal begins'
require "$SHELL_QML" 'interval: 32'     'Link material remains mapped too long after close'
require "$SHELL_QML" 'visible: root.presented'     'Link material/catcher surfaces do not unmap after dismissal'
require "$SHELL_QML" 'namespace: "maho-link-keepalive"'     'Link warm residency no longer uses the tiny unblurred keepalive'
require "$SHELL_QML" 'implicitWidth: 1'     'Link keepalive is not bounded to a tiny compositor surface'
echo PASS

echo '=== Bluetooth final-geometry reveal ==='
require "$LINK_VIEW" 'Behavior on height {' \
    'Link no longer has bounded height motion'
require "$LINK_VIEW" 'enabled: root.shown' \
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
