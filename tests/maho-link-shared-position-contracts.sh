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
require_text 'function placementSpanX()' \
    'shared placement has no mode-independent horizontal coordinate space'
require_text 'function placementSpanY()' \
    'shared placement has no mode-independent vertical coordinate space'
require_text 'overlay.width - surfaceMarginX * 2' \
    'horizontal coordinate space still depends on panel geometry'
require_text 'overlay.height - surfaceMarginY * 2' \
    'vertical coordinate space still depends on panel geometry'
require_text 'placementSpanX() * clamp(Number(linkPlacement.normalizedX), 0, 1)' \
    'stored X is not mapped through the shared monitor coordinate space'
require_text 'placementSpanY() * clamp(Number(linkPlacement.normalizedY), 0, 1)' \
    'stored Y is not mapped through the shared monitor coordinate space'
require_text '(linkSurface.x - surfaceMarginX) / placementSpanX()' \
    'persisted X is not independent of the current Link panel width'
require_text '(linkSurface.y - surfaceMarginY) / placementSpanY()' \
    'persisted Y is not independent of the current Link panel height'
reject_text 'const spanY = Math.max(0, maxY - surfaceMarginY)' \
    'shared Y still normalizes against a panel-height-dependent maximum'
reject_text 'const spanX = Math.max(0, maxX - surfaceMarginX)' \
    'shared X still normalizes against a panel-width-dependent maximum'

printf 'PASS  Maho Link Wi-Fi/Bluetooth share one mode-independent top-left position\n'
