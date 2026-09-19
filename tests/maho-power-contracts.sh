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
require_text "$VIEW" 'return action === "restart" || action === "shutdown"' 'only restart and shutdown should require confirmation'
reject_text "$VIEW" 'action === "logout" || action === "restart" || action === "shutdown"' 'Log Out still requires a second confirmation click'
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
require_text "$STANDALONE" 'PowerBackdrop { id: backdrop; active: root.presented }' 'standalone blur carrier is not synchronized with presentation state'
require_text "$STANDALONE" 'WlrLayershell.namespace: "maho-power"' 'standalone namespace missing'
require_text "$STANDALONE" 'WlrLayershell.layer: WlrLayer.Overlay' 'standalone is not an Overlay surface'
require_text "$STANDALONE" 'WlrKeyboardFocus.Exclusive' 'standalone does not own keyboard navigation while open'
require_text "$STANDALONE" 'width: Math.min(860' 'standalone target width clamp missing'
require_text "$STANDALONE" 'height: Math.min(570' 'standalone target height clamp missing'
require_text "$STANDALONE" 'theme.alpha(theme.background, 0.055)' 'standalone background is over-dimmed instead of luminous blur'
reject_text "$STANDALONE" 'id: depthShadow' 'standalone rear depth-shadow slab returned'
reject_text "$STANDALONE" 'width: powerView.width + 26' 'standalone rear shadow geometry returned'
reject_text "$STANDALONE" 'Qt.rgba(0, 0, 0, 0.16)' 'standalone black rear slab returned'
require_text "$BACKDROP" 'property bool active: true' 'Power backdrop lacks explicit lifecycle authority'
require_text "$BACKDROP" 'visible: root.active' 'Power backdrop can remain mapped after the panel starts closing'
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
require_text "$RUNTIME" 'queue_logout()' 'Log Out does not escape the caller cgroup before graphical teardown'
require_text "$RUNTIME" '--collect' 'Log Out transient worker is not collected after completion'
require_text "$RUNTIME" '--property=Type=exec' 'Log Out transient worker lacks execution confirmation'
require_text "$RUNTIME" '"$HOME/.local/bin/maho-power" logout-worker' 'Log Out does not delegate to the independent worker'
require_text "$RUNTIME" 'logout_worker()' 'Log Out worker implementation missing'
require_text "$RUNTIME" '"$session_controller" stop || return 1' 'Log Out worker does not stop the Maho graphical target before compositor exit'
logout_stop_line="$(grep -nF '"$session_controller" stop || return 1' "$RUNTIME" | head -1 | cut -d: -f1)"
logout_exit_line="$(grep -nF 'exec "$hyprctl_bin" dispatch' "$RUNTIME" | head -1 | cut -d: -f1)"
[ -n "$logout_stop_line" ] && [ -n "$logout_exit_line" ] && [ "$logout_stop_line" -lt "$logout_exit_line" ] \
    || fail 'Log Out worker exits Hyprland before the Maho graphical target is stopped'
require_text "$RUNTIME" 'exec "$hyprctl_bin" dispatch' 'Log Out worker does not dispatch through the captured Hyprland client'
require_text "$RUNTIME" "hl.dsp.exit()" 'Log Out worker does not use current Hyprland Lua dispatcher syntax'
require_text "$RUNTIME" 'exec systemctl reboot' 'Restart action missing'
require_text "$RUNTIME" 'exec systemctl poweroff' 'Shut Down action missing'
require_text "$RUNTIME" 'maho-power action {lock|sleep|switch-user|logout|restart|shutdown}' 'runtime action surface is not explicitly bounded'
reject_text "$RUNTIME" 'eval "$action"' 'runtime must not evaluate action input'
reject_text "$RUNTIME" 'bash -c "$action"' 'runtime must not execute action input as shell source'
echo '=== logout transient worker execution ==='
TMP_LOGOUT="$(mktemp -d)"
trap 'rm -rf "$TMP_LOGOUT"' EXIT
mkdir -p "$TMP_LOGOUT/home/.local/bin" "$TMP_LOGOUT/bin"
cat >"$TMP_LOGOUT/bin/systemd-run" <<'EOF_SYSTEMD_RUN'
#!/usr/bin/env bash
printf '%s\n' "$@" >"$MAHO_TEST_SYSTEMD_RUN_LOG"
EOF_SYSTEMD_RUN
cat >"$TMP_LOGOUT/bin/session" <<'EOF_SESSION'
#!/usr/bin/env bash
printf 'session:%s\n' "$1" >>"$MAHO_TEST_WORKER_LOG"
EOF_SESSION
cat >"$TMP_LOGOUT/bin/hyprctl" <<'EOF_HYPRCTL'
#!/usr/bin/env bash
printf 'hyprctl:%s\n' "$*" >>"$MAHO_TEST_WORKER_LOG"
EOF_HYPRCTL
chmod +x "$TMP_LOGOUT/bin/systemd-run" "$TMP_LOGOUT/bin/session" "$TMP_LOGOUT/bin/hyprctl"
printf '#!/usr/bin/env bash\nexit 0\n' >"$TMP_LOGOUT/home/.local/bin/maho-power"
chmod +x "$TMP_LOGOUT/home/.local/bin/maho-power"
MAHO_TEST_SYSTEMD_RUN_LOG="$TMP_LOGOUT/systemd-run.log" \
MAHO_POWER_SYSTEMD_RUN="$TMP_LOGOUT/bin/systemd-run" \
HOME="$TMP_LOGOUT/home" \
XDG_RUNTIME_DIR=/run/user/1000 \
WAYLAND_DISPLAY=wayland-test \
HYPRLAND_INSTANCE_SIGNATURE=instance-test \
    bash "$RUNTIME" action logout
require_text "$TMP_LOGOUT/systemd-run.log" '--user' 'logout did not use the user manager'
require_text "$TMP_LOGOUT/systemd-run.log" '--collect' 'logout transient worker is not collectable'
require_text "$TMP_LOGOUT/systemd-run.log" '--setenv=WAYLAND_DISPLAY=wayland-test' 'logout worker lost Wayland display authority'
require_text "$TMP_LOGOUT/systemd-run.log" '--setenv=HYPRLAND_INSTANCE_SIGNATURE=instance-test' 'logout worker lost Hyprland instance authority'
require_text "$TMP_LOGOUT/systemd-run.log" 'logout-worker' 'logout did not queue the worker entrypoint'
MAHO_TEST_WORKER_LOG="$TMP_LOGOUT/worker.log" \
MAHO_POWER_SESSION_CONTROLLER="$TMP_LOGOUT/bin/session" \
MAHO_POWER_HYPRCTL="$TMP_LOGOUT/bin/hyprctl" \
HOME="$TMP_LOGOUT/home" \
    bash "$RUNTIME" logout-worker
[ "$(sed -n '1p' "$TMP_LOGOUT/worker.log")" = 'session:stop' ] \
    || fail 'logout worker did not stop the graphical target first'
[ "$(sed -n '2p' "$TMP_LOGOUT/worker.log")" = "hyprctl:dispatch hl.dsp.exit()" ] \
    || fail 'logout worker did not exit Hyprland second'
rm -rf "$TMP_LOGOUT"
trap - EXIT
echo PASS

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
require_text "$BINDS" 'mainMod .. " + E"' 'SUPER+E binding missing'
require_text "$BINDS" '"$HOME/.local/bin/maho-files" run "$HOME"' 'SUPER+E does not route directly to native Maho Files'
reject_text "$BINDS" 'xdg-open "$HOME"' 'SUPER+E still delegates Home to the MIME handler and can open a browser'
echo PASS

echo '=== scope guard ==='
branch_context="${GITHUB_HEAD_REF:-$(git -C "$ROOT" branch --show-current 2>/dev/null || true)}"
case "$branch_context" in
  feat/maho-power-session|feat/maho-power-session-*|fix/maho-power-*)
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
    ;;
  *)
    echo "INFO scope guard not applicable to aggregate branch: ${branch_context:-detached}"
    ;;
esac
echo PASS

echo 'ALL MAHO POWER CONTRACTS PASS'
