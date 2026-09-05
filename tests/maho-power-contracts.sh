#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
VIEW="$ROOT/config/quickshell/maho-shell/MahoPowerView.qml"
THEME="$ROOT/config/quickshell/maho-shell/MahoTheme.qml"
CENTER="$ROOT/config/quickshell/maho-shell/ControlCenter.qml"
STANDALONE="$ROOT/config/quickshell/maho-power/shell.qml"
STANDALONE_VIEW="$ROOT/config/quickshell/maho-power/MahoPowerView.qml"
STANDALONE_THEME="$ROOT/config/quickshell/maho-power/MahoTheme.qml"
BACKDROP="$ROOT/config/quickshell/maho-power/PowerBackdrop.qml"
RUNTIME="$ROOT/bin/maho-power"
INSTALLER="$ROOT/bin/maho-power-install"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_file() {
    [ -r "$1" ] || fail "missing file: $1"
}

require_text() {
    local file="$1" text="$2" message="$3"
    grep -Fq -- "$text" "$file" || fail "$message"
}

reject_text() {
    local file="$1" text="$2" message="$3"
    if grep -Fq -- "$text" "$file"; then
        fail "$message"
    fi
}

for file in \
    "$VIEW" \
    "$THEME" \
    "$CENTER" \
    "$STANDALONE" \
    "$STANDALONE_VIEW" \
    "$STANDALONE_THEME" \
    "$BACKDROP" \
    "$RUNTIME" \
    "$INSTALLER" \
    "$BINDS"
do
    require_file "$file"
done

echo '=== runtime syntax ==='
bash -n "$RUNTIME"
bash -n "$INSTALLER"
echo PASS

echo '=== shared visual authority ==='
require_text "$VIEW" 'text: "Power & Session"' 'shared Power title missing'
require_text "$VIEW" 'text: "Choose an action"' 'standalone subtitle missing'
require_text "$VIEW" 'property bool compact: false' 'shared view does not support embedded compact mode'
require_text "$VIEW" 'implicitWidth: compact ? 360 : 860' 'target width geometry drifted'
require_text "$VIEW" 'implicitHeight: compact ? 276 : 570' 'target height geometry drifted'
require_text "$VIEW" 'readonly property int outerRadius: compact ? 20 : 34' 'target outer silhouette radius drifted'
require_text "$VIEW" 'root.compact ? 0.90 : 0.34' 'glass material opacity drifted away from translucent target'
require_text "$VIEW" 'root.compact ? 0.075 : 0.225' 'target blue-violet top sheen missing'
require_text "$VIEW" 'root.theme.foreground, root.compact ? 0.075 : 0.145' 'soft light rim missing or replaced by a dark perimeter'
require_text "$VIEW" 'id: ambientRim' 'subtle palette ambient rim missing'
reject_text "$VIEW" 'id: shadow' 'rear black shadow slab returned inside shared Power view'
reject_text "$VIEW" 'id: halo' 'legacy extra halo ring returned'
require_text "$VIEW" 'root.theme.surfaceHigh, root.theme.primary, 0.39' 'Lock focus glass treatment missing'
require_text "$VIEW" 'root.compact ? 0.82 : 0.26' 'normal action cards drifted back toward opaque gray'
require_text "$VIEW" 'glyph: "󰖔"' 'Sleep did not use the crescent target icon'
require_text "$VIEW" 'glyph: "󰀄"' 'Switch User did not use the clean person target icon'
require_text "$VIEW" 'action: "lock"' 'Lock action missing'
require_text "$VIEW" 'action: "sleep"' 'Sleep action missing'
require_text "$VIEW" 'action: "switch-user"' 'Switch User action missing'
require_text "$VIEW" 'action: "restart"' 'Restart action missing'
require_text "$VIEW" 'action: "logout"' 'Log Out action missing'
require_text "$VIEW" 'action: "shutdown"' 'Shut Down action missing'
require_text "$VIEW" 'title: "Lock"' 'Lock label missing'
require_text "$VIEW" 'title: "Sleep"' 'Sleep label missing'
require_text "$VIEW" 'title: "Switch User"' 'Switch User label missing'
require_text "$VIEW" 'title: "Restart"' 'Restart label missing'
require_text "$VIEW" 'title: "Log Out"' 'Log Out label missing'
require_text "$VIEW" 'title: "Shut Down"' 'Shut Down label missing'
require_text "$VIEW" 'selectedIndex: 0' 'Lock is not the initial keyboard selection'
require_text "$VIEW" 'property bool danger: false' 'danger visual state missing'
require_text "$VIEW" 'danger: true' 'Shut Down danger state missing'
require_text "$VIEW" 'requiresConfirmation(action)' 'destructive confirmation gate missing'
require_text "$VIEW" 'Press again to confirm' 'destructive second-activation feedback missing'
reject_text "$VIEW" 'Esc to close' 'rejected Esc instruction returned'
reject_text "$VIEW" 'Enter to confirm' 'rejected Enter instruction returned'
cmp -s "$VIEW" "$STANDALONE_VIEW" || fail 'standalone Power view drifted from Edge visual authority'
cmp -s "$THEME" "$STANDALONE_THEME" || fail 'standalone theme drifted from Maho Edge theme authority'
echo PASS

echo '=== standalone overlay ==='
reject_text "$STANDALONE" 'import "../maho-shell"' 'standalone imports outside its Quickshell config root'
require_text "$STANDALONE" 'MahoTheme { id: theme }' 'standalone local Maho theme type missing'
require_text "$STANDALONE" 'MahoPowerView {' 'standalone does not use packaged Power view'
require_text "$STANDALONE" 'PowerBackdrop {' 'standalone blur carrier missing'
require_text "$STANDALONE" 'WlrLayershell.namespace: "maho-power"' 'standalone namespace missing'
require_text "$STANDALONE" 'WlrLayershell.layer: WlrLayer.Overlay' 'standalone is not an Overlay surface'
require_text "$STANDALONE" 'WlrKeyboardFocus.Exclusive' 'standalone does not own keyboard navigation while open'
require_text "$STANDALONE" 'width: Math.min(860' 'standalone target width clamp missing'
require_text "$STANDALONE" 'height: Math.min(570' 'standalone target height clamp missing'
require_text "$STANDALONE" 'theme.alpha(theme.background, 0.055)' 'standalone background is over-dimmed instead of luminous blur'
reject_text "$STANDALONE" 'id: depthShadow' 'standalone rear depth-shadow slab returned'
reject_text "$STANDALONE" 'width: powerView.width + 26' 'standalone rear shadow geometry returned'
reject_text "$STANDALONE" 'Qt.rgba(0, 0, 0, 0.16)' 'standalone black rear slab returned'
require_text "$BACKDROP" 'exclusionMode: ExclusionMode.Ignore' 'backdrop can be displaced by Edge reservation'
require_text "$BACKDROP" 'mask: Region {}' 'backdrop can intercept input'
require_text "$BACKDROP" 'WlrLayershell.namespace: "maho-power-backdrop"' 'blur namespace missing'
require_text "$BACKDROP" 'WlrLayershell.layer: WlrLayer.Top' 'blur carrier must sit below Overlay UI'
require_text "$BACKDROP" 'Qt.rgba(0, 0, 0, 0.008)' 'stable blur carrier alpha drifted'
echo PASS

echo '=== Edge dropdown integration ==='
require_text "$CENTER" 'property bool powerExpanded: false' 'Edge Power expansion state missing'
require_text "$CENTER" 'readonly property real quickActionsTop: panelColumn.y + quickActions.y' 'Power dropdown lacks layout-independent quick-action anchor'
require_text "$CENTER" 'id: quickActions' 'bottom action anchor row missing'
require_text "$CENTER" 'id: powerDropdown' 'Power is not implemented as an overlay dropdown'
require_text "$CENTER" 'y: center.quickActionsTop - height - 7' 'Power dropdown is not attached tightly above the Power action row'
require_text "$CENTER" 'z: 40' 'Power dropdown does not float above Edge content'
require_text "$CENTER" 'id: powerScrim' 'Power dropdown lacks local backdrop separation'
require_text "$CENTER" 'center.theme.alpha(center.theme.background, 0.16)' 'Power dropdown backdrop separation is too weak'
require_text "$CENTER" 'MahoPowerView {' 'expanded Edge does not reuse shared Power view'
require_text "$CENTER" 'compact: true' 'Edge does not use compact Power geometry'
require_text "$CENTER" 'labelText: "Power"' 'bottom-left generic Power tile missing'
require_text "$CENTER" 'activeState: center.powerExpanded' 'Power tile does not expose active state'
require_text "$CENTER" 'center.powerExpanded = !center.powerExpanded' 'Power tile does not toggle sheet'
require_text "$CENTER" 'id: powerPointer' 'Power sheet pointer missing'
require_text "$CENTER" 'x: (((powerDropdown.width - 14) / 3) - width) / 2' 'Power sheet pointer is not centered over the Power tile'
require_text "$CENTER" 'anchors.topMargin: -7' 'Power pointer is not visually fused into the dropdown edge'
require_text "$CENTER" 'border.width: 0' 'Power pointer reverted to an outlined kite'
reject_text "$CENTER" 'x: 42' 'legacy hard-coded Power pointer alignment returned'
reject_text "$CENTER" 'id: powerExpansion' 'legacy in-flow Power expansion returned'
reject_text "$CENTER" 'height: center.powerExpanded ? compactPower.implicitHeight + 8 : 0' 'Power menu is mutating Control Center layout height'
if grep -Fq 'labelText: "Lock"' "$CENTER"; then
    fail 'legacy direct Lock quick tile returned'
fi
require_text "$CENTER" 'labelText: "Capture"' 'Capture quick action regressed'
require_text "$CENTER" 'labelText: "Launcher"' 'Launcher quick action regressed'
echo PASS

echo '=== bounded action authority ==='
require_text "$RUNTIME" 'case "$action" in' 'Power action whitelist missing'
require_text "$RUNTIME" 'exec "$HOME/.local/bin/maho-lock"' 'Lock does not route to secure Maho Lock'
reject_text "$RUNTIME" 'hyprlock' 'Power must not bypass secure Maho Lock with hyprlock'
require_text "$RUNTIME" 'exec systemctl suspend' 'Sleep action missing'
require_text "$RUNTIME" 'SwitchToGreeter' 'Switch User display-manager action missing'
require_text "$RUNTIME" 'exec hyprctl dispatch exit' 'Log Out action missing'
require_text "$RUNTIME" 'exec systemctl reboot' 'Restart action missing'
require_text "$RUNTIME" 'exec systemctl poweroff' 'Shut Down action missing'
require_text "$RUNTIME" 'maho-power action {lock|sleep|switch-user|logout|restart|shutdown}' 'runtime action surface is not explicitly bounded'
reject_text "$RUNTIME" 'eval "$action"' 'runtime must not evaluate action input'
reject_text "$RUNTIME" 'bash -c "$action"' 'runtime must not execute action input as shell source'
require_text "$RUNTIME" 'match = { namespace = "maho-power-backdrop" }' 'material rule is not scoped to Power blur carrier'
require_text "$RUNTIME" 'ignore_alpha = 0.001' 'blur threshold contract drifted'
echo PASS

echo '=== transactional install contract ==='
require_text "$INSTALLER" 'RUNTIME_MARKER="managed-by-maho-power-install-v1"' 'managed runtime marker missing'
require_text "$INSTALLER" 'WRAPPER_MARKER="# managed-by: maho-power-install v1"' 'managed wrapper marker missing'
require_text "$INSTALLER" 'BACKUP_ROOT="$STATE_HOME/maho/power-install/backups"' 'timestamped backup root missing'
require_text "$INSTALLER" 'refusing unmanaged command collision' 'installer can overwrite unmanaged command'
require_text "$INSTALLER" 'refusing unmanaged runtime collision' 'installer can overwrite unmanaged runtime'
require_text "$INSTALLER" 'SUPER+SHIFT+P is already owned outside' 'installer does not guard bind collisions'
require_text "$INSTALLER" 'restore_snapshot "$backup"' 'automatic rollback path missing'
require_text "$INSTALLER" 'cmp -s "$SOURCE_CENTER" "$LIVE_CENTER"' 'live Edge source verification missing'
require_text "$INSTALLER" 'cmp -s "$SOURCE_VIEW" "$LIVE_VIEW"' 'live shared view verification missing'
require_text "$INSTALLER" 'hyprctl configerrors' 'post-install Hyprland config verification missing'
require_text "$INSTALLER" 'systemctl --user restart maho-shell.service' 'installer does not refresh active Edge after source replacement'
reject_text "$INSTALLER" 'pkill -f' 'installer must not broadly kill Quickshell processes'
echo PASS

echo '=== keybind authority ==='
require_text "$BINDS" '-- maho-power-bind:begin' 'managed Power bind start marker missing'
require_text "$BINDS" '-- maho-power-bind:end' 'managed Power bind end marker missing'
require_text "$BINDS" 'mainMod .. " + SHIFT + P"' 'SUPER+SHIFT+P binding missing'
require_text "$BINDS" '"$HOME/.local/bin/maho-power" open' 'Power keybind does not invoke bounded runtime'
[ "$(grep -Fc 'mainMod .. " + SHIFT + P"' "$BINDS")" -eq 1 ] || fail 'Power keybind is duplicated'
require_text "$BINDS" 'mainMod .. " + CTRL + L"' 'secure Maho Lock binding regressed'
require_text "$BINDS" '"$HOME/.local/bin/maho-lock"' 'secure Maho Lock command regressed'
echo PASS

echo '=== scope guard ==='
for forbidden in \
    config/quickshell/maho-link \
    config/quickshell/maho-notify \
    config/quickshell/maho-launcher \
    config/quickshell/maho-shell/dock-shell.qml \
    apps/maho-files
 do
    if git -C "$ROOT" diff --name-only 32833a47df0483da70d5b7a9dd7f20dd498616ec...HEAD -- "$forbidden" | grep -q .; then
        fail "Power branch touched unrelated scope: $forbidden"
    fi
 done
echo PASS

echo 'ALL MAHO POWER CONTRACTS PASS'
