#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL="$ROOT/config/quickshell/maho-link/shell.qml"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

require_text() {
    local needle="$1" message="$2"
    grep -Fq -- "$needle" "$SHELL" || fail "$message"
}

reject_text() {
    local needle="$1" message="$2"
    if grep -Fq -- "$needle" "$SHELL"; then
        fail "$message"
    fi
}

require_text 'readonly property string linkPlacementPath: stateBase + "/maho-link-position.json"' \
    'Link modes do not share one product-level placement file'
reject_text 'Quickshell.statePath("link-position.json")' \
    'Link placement regressed to runtime-scoped Quickshell state'

# Same-monitor restoration must be exact in physical pixels. Wi-Fi and
# Bluetooth have different panel dimensions, so normalized-only restoration is
# not sufficient near monitor edges.
require_text 'function canRestoreExactPixels()' \
    'Link has no exact same-monitor restoration path'
require_text 'property int version: 2' \
    'Link placement state did not advance to the exact-pixel schema'
require_text 'property real pixelX: -1' \
    'shared placement does not persist exact X'
require_text 'property real pixelY: -1' \
    'shared placement does not persist exact Y'
require_text 'property real monitorWidth: -1' \
    'shared placement does not remember monitor width'
require_text 'property real monitorHeight: -1' \
    'shared placement does not remember monitor height'
require_text 'targetX = Number(linkPlacement.pixelX)' \
    'Wi-Fi/Bluetooth do not restore the same exact X on unchanged geometry'
require_text 'targetY = Number(linkPlacement.pixelY)' \
    'Wi-Fi/Bluetooth do not restore the same exact Y on unchanged geometry'
require_text 'linkPlacement.pixelX = linkSurface.x' \
    'drag completion does not save exact X'
require_text 'linkPlacement.pixelY = linkSurface.y' \
    'drag completion does not save exact Y'
require_text 'linkPlacement.monitorWidth = overlay.width' \
    'exact-pixel state is not scoped to current monitor geometry'
require_text 'linkPlacement.monitorHeight = overlay.height' \
    'exact-pixel state is not scoped to current monitor geometry'

# Keep normalized coordinates as a resolution/output fallback. They remain
# mode-independent because they are normalized against monitor margin space,
# never against the current panel width/height.
require_text 'function placementSpanX()' \
    'shared placement has no mode-independent horizontal fallback space'
require_text 'function placementSpanY()' \
    'shared placement has no mode-independent vertical fallback space'
require_text 'overlay.width - surfaceMarginX * 2' \
    'horizontal fallback coordinate space depends on panel geometry'
require_text 'overlay.height - surfaceMarginY * 2' \
    'vertical fallback coordinate space depends on panel geometry'
require_text 'placementSpanX() * clamp(Number(linkPlacement.normalizedX), 0, 1)' \
    'resolution fallback X is missing'
require_text 'placementSpanY() * clamp(Number(linkPlacement.normalizedY), 0, 1)' \
    'resolution fallback Y is missing'
require_text '(linkSurface.x - surfaceMarginX) / placementSpanX()' \
    'normalized fallback X is not updated after drag'
require_text '(linkSurface.y - surfaceMarginY) / placementSpanY()' \
    'normalized fallback Y is not updated after drag'
reject_text 'const spanY = Math.max(0, maxY - surfaceMarginY)' \
    'shared Y still normalizes against a panel-height-dependent maximum'
reject_text 'const spanX = Math.max(0, maxX - surfaceMarginX)' \
    'shared X still normalizes against a panel-width-dependent maximum'

printf 'PASS  Maho Link Wi-Fi/Bluetooth share one exact same-monitor top-left position\n'
