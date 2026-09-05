#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_QML="$ROOT/config/quickshell/maho-power/shell.qml"
BACKDROP="$ROOT/config/quickshell/maho-power/PowerBackdrop.qml"
RUNTIME="$ROOT/bin/maho-power"

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

for file in "$SHELL_QML" "$BACKDROP" "$RUNTIME"; do
    [ -r "$file" ] || fail "missing file: $file"
done

echo '=== Power compositor sequencing ==='
require "$SHELL_QML" 'property bool backdropActive: true' \
    'blur carrier is not mapped before foreground presentation'
require "$SHELL_QML" 'PowerBackdrop { id: backdrop; active: root.backdropActive }' \
    'Power backdrop still follows foreground presentation directly'
require "$SHELL_QML" 'Component.onCompleted: Qt.callLater(function() {' \
    'foreground is not deferred until after blur carrier creation'
require "$SHELL_QML" 'backdropActive = false' \
    'dismissal does not unmap blur carrier immediately'
require "$SHELL_QML" 'closeTimer.stop()' \
    'reopen-during-close cannot recover the same coherent surface'
reject "$SHELL_QML" 'PowerBackdrop { id: backdrop; active: root.presented }' \
    'blur carrier mapping is coupled to animated foreground state'
reject "$SHELL_QML" 'id: presentTimer' \
    'legacy timer-driven simultaneous blur/panel reveal returned'

echo PASS

echo '=== Stable dedicated blur plane ==='
require "$BACKDROP" 'WlrLayershell.namespace: "maho-power-backdrop"' \
    'dedicated Power backdrop namespace missing'
require "$BACKDROP" 'WlrLayershell.layer: WlrLayer.Top' \
    'Power backdrop is not below Overlay UI'
require "$BACKDROP" 'mask: Region {}' \
    'Power backdrop can intercept input'
require "$BACKDROP" 'Qt.rgba(0, 0, 0, 0.008)' \
    'Power backdrop no longer uses stable tiny-alpha carrier'
require "$RUNTIME" 'match = { namespace = "maho-power-backdrop" }' \
    'Power blur rule is not scoped to the dedicated carrier'
require "$RUNTIME" 'ignore_alpha = 0.001' \
    'Power blur threshold drifted away from stable carrier contract'

echo PASS

echo 'ALL MAHO POWER COMPOSITOR CONTRACTS PASS'
