#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NOTIFY="$ROOT/config/quickshell/maho-notify"
THEME="$NOTIFY/NotifyTheme.qml"
CARD="$NOTIFY/NotificationCard.qml"
CENTER="$NOTIFY/NotificationCenter.qml"
ROW="$NOTIFY/HistoryRow.qml"
SHELL="$NOTIFY/shell.qml"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}
reject_text() {
    local file="$1" needle="$2" message="$3"
    if grep -Fq -- "$needle" "$file"; then fail "$message"; fi
}

echo "=== Maho Notify glass family ==="
require_text "$THEME" 'function stableAccent' "stable wallpaper accent normalization missing"
require_text "$THEME" 'insetColor: mix(surfaceHigh, background, 0.36)' "Notify inset material drifted from Maho family"
require_text "$THEME" 'familyShell: mix(surfaceHigh, background, 0.54)' "Notify shell material drifted from Maho family"
require_text "$THEME" 'popupFill: alpha(familyShell, 0.78)' "popup is not authored translucent glass"
require_text "$THEME" 'centerFill: alpha(familyShell, 0.74)' "center is not authored translucent glass"
require_text "$THEME" 'shellRim: alpha(foreground, 0.095)' "glass whisper rim missing"
require_text "$THEME" 'shellTopSpecular: alpha(foreground, 0.034)' "glass top reflection missing"
require_text "$THEME" 'controlFill:' "shared control tier missing"
require_text "$THEME" 'rowSelected:' "raised row tier missing"
require_text "$THEME" 'divider: alpha(foreground, 0.040)' "quiet divider tier missing"
reject_text "$CARD" 'theme.alpha(theme.surfaceHigh, 0.965)' "old opaque popup slab returned"
reject_text "$CENTER" 'theme.alpha(theme.surfaceHigh, 0.975)' "old opaque center slab returned"

echo "PASS"

echo "=== popup material and motion ==="
require_text "$CARD" 'color: theme.popupFill' "popup does not use shared glass shell"
require_text "$CARD" 'clip: true' "popup material is not radius-clipped"
require_text "$CARD" 'gradient: Gradient {' "popup material depth missing"
require_text "$CARD" 'theme.shellTopSpecular' "popup top reflection missing"
require_text "$CARD" 'theme.shellBottomShade' "popup lower material depth missing"
require_text "$CARD" 'Behavior on scale' "popup hover motion missing"
require_text "$CARD" 'easing.type: Easing.OutCubic' "popup motion is not calm OutCubic"
require_text "$CARD" 'theme.actionFill' "actions do not use interactive glass tier"
require_text "$CARD" 'theme.controlPressed' "pressed feedback missing"
echo "PASS"

echo "=== center material and controls ==="
require_text "$CENTER" 'color: theme.centerFill' "center does not use shared glass shell"
require_text "$CENTER" 'clip: true' "center material is not radius-clipped"
require_text "$CENTER" 'theme.shellTopSpecular' "center top reflection missing"
require_text "$CENTER" 'theme.shellAccentWash' "center restrained accent wash missing"
require_text "$CENTER" 'theme.controlFill' "center neutral control tier missing"
require_text "$CENTER" 'theme.actionFill' "DND active tier missing"
require_text "$CENTER" 'theme.divider' "center separator is visually loud or ad hoc"
require_text "$CENTER" 'duration: center.shown ? 210 : 155' "accepted restrained center motion changed"
echo "PASS"

echo "=== history hierarchy ==="
require_text "$ROW" 'theme.rowSelected' "selected history glass tier missing"
require_text "$ROW" 'theme.rowUnread' "unread history glass tier missing"
require_text "$ROW" 'theme.rowHover' "history hover glass tier missing"
require_text "$ROW" 'theme.rowActiveRim' "history active rim missing"
require_text "$ROW" 'theme.textPrimary' "history primary text hierarchy missing"
require_text "$ROW" 'theme.textSecondary' "history secondary text hierarchy missing"
require_text "$ROW" 'Behavior on color' "history transitions missing"
require_text "$ROW" 'Easing.OutCubic' "history motion is not calm OutCubic"
echo "PASS"

echo "=== compositor safety ==="
# Notify still owns full-screen PanelWindows for placement/input masks. A blur
# layer-rule against those namespaces would blur the desktop outside the cards.
if grep -RnsE 'layer_rule|blur[[:space:]]*=[[:space:]]*true|ignore_alpha' "$NOTIFY" "$ROOT/bin/maho-notify" --include='*.qml' --include='maho-notify'; then
    fail "Notify introduced compositor blur while its layer surfaces are full-screen"
fi
require_text "$SHELL" 'mask: Region { item: popupStack }' "popup input remains unconstrained"
require_text "$SHELL" 'mask: Region { item: centerSurface }' "center input remains unconstrained"
echo "PASS"

echo "ALL MAHO NOTIFY GLASS CONTRACTS PASS"
