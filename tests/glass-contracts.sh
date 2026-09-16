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
require_text "$THEME" 'familyShell: mix(surfaceHigh, background, 0.58)' "Notify v3 shell material drifted"
require_text "$THEME" 'popupFill: alpha(familyShell, 0.86)' "popup readability density regressed"
require_text "$THEME" 'centerFill: alpha(familyShell, 0.84)' "center readability density regressed"
require_text "$THEME" 'textBody: alpha(foreground, 0.84)' "body text hierarchy missing"
require_text "$THEME" 'textSecondary: alpha(muted, 0.88)' "secondary text is too faint"
require_text "$THEME" 'shellRim: alpha(foreground, 0.125)' "v3 shell rim missing"
require_text "$THEME" 'shellTopSpecular: alpha(foreground, 0.050)' "v3 glass top reflection missing"
require_text "$THEME" 'toolbarFill:' "nested toolbar glass tier missing"
require_text "$THEME" 'sectionFill:' "nested history-well glass tier missing"
require_text "$THEME" 'controlFill:' "shared control tier missing"
require_text "$THEME" 'rowSelected:' "raised row tier missing"
require_text "$THEME" 'divider: alpha(foreground, 0.060)' "quiet divider tier missing"
reject_text "$CARD" 'theme.alpha(theme.surfaceHigh, 0.965)' "old opaque popup slab returned"
reject_text "$CENTER" 'theme.alpha(theme.surfaceHigh, 0.975)' "old opaque center slab returned"

echo "PASS"

echo "=== popup material and motion ==="
require_text "$CARD" 'color: theme.popupFill' "popup does not use shared glass shell"
require_text "$CARD" 'clip: true' "popup material is not radius-clipped"
require_text "$CARD" 'gradient: Gradient {' "popup material depth missing"
require_text "$CARD" 'theme.shellTopSpecular' "popup top reflection missing"
require_text "$CARD" 'theme.shellBottomShade' "popup lower material depth missing"
require_text "$CARD" 'color: theme.textBody' "popup body readability hierarchy missing"
require_text "$CARD" 'font.pixelSize: 15' "popup title hierarchy regressed"
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
require_text "$CENTER" 'color: theme.toolbarFill' "toolbar is not a nested glass plane"
require_text "$CENTER" 'color: theme.sectionFill' "history well is not a nested glass plane"
require_text "$CENTER" 'theme.controlFill' "center neutral control tier missing"
require_text "$CENTER" 'theme.actionFill' "DND active tier missing"
require_text "$CENTER" 'theme.divider' "center separator is visually loud or ad hoc"
require_text "$CENTER" 'font.pixelSize: 19' "center title hierarchy regressed"
require_text "$CENTER" 'duration: center.shown ? 210 : 155' "accepted restrained center motion changed"
echo "PASS"

echo "=== persistent draggable notification center ==="
require_text "$SHELL" 'Quickshell.statePath("center-position.json")' "notification center position is not persisted"
require_text "$SHELL" 'property real normalizedX: 0.5' "notification center horizontal position is not resolution-adaptive"
require_text "$SHELL" 'property real normalizedY: 0.5' "notification center vertical position is not resolution-adaptive"
require_text "$SHELL" 'function persistCenterPlacement()' "notification center drag completion is not persisted"
require_text "$SHELL" 'drag.target: centerLoader.item' "notification center is not the drag target"
require_text "$SHELL" 'width: centerLoader.item ? Math.max(100, centerLoader.item.width - 220) : 0' "notification center drag handle is not constrained to the safe title region"
require_text "$SHELL" 'drag.minimumX: root.centerMarginX' "notification center drag is not clamped horizontally"
require_text "$SHELL" 'drag.maximumY: root.maximumCenterY()' "notification center drag is not clamped vertically"
require_text "$SHELL" 'if (centerPlacement.valid)' "persisted notification center placement does not override first-run Edge placement"
require_text "$SHELL" 'Qt.callLater(root.applyCenterPlacement)' "notification center placement is not restored when opened"
echo "PASS"

echo "=== history hierarchy ==="
require_text "$ROW" 'theme.rowSelected' "selected history glass tier missing"
require_text "$ROW" 'theme.rowUnread' "unread history glass tier missing"
require_text "$ROW" 'theme.rowHover' "history hover glass tier missing"
require_text "$ROW" 'theme.rowActiveRim' "history active rim missing"
require_text "$ROW" 'theme.textPrimary' "history primary text hierarchy missing"
require_text "$ROW" 'theme.textBody' "history body readability hierarchy missing"
require_text "$ROW" 'theme.textMuted' "history metadata hierarchy missing"
require_text "$ROW" 'id: unreadDot' "history unread affordance missing"
require_text "$ROW" 'font.pixelSize: 13' "history title hierarchy regressed"
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
require_text "$SHELL" 'mask: Region { item: centerLoader.item }' "center input remains unconstrained"
echo "PASS"

echo "ALL MAHO NOTIFY GLASS CONTRACTS PASS"
