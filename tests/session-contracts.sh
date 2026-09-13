#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_LUA="$ROOT/config/hypr/maho/core/session.lua"
HYPRLAND_LUA="$ROOT/config/hypr/hyprland.lua"
SESSION_BIN="$ROOT/bin/maho-session"
TARGET="$ROOT/systemd/user/maho-hyprland-session.target"
AWWW_UNIT="$ROOT/systemd/user/maho-awww-daemon.service"
WALLPAPER_UNIT="$ROOT/systemd/user/maho-wallpaper.service"
SHELL_UNIT="$ROOT/systemd/user/maho-shell.service"
DOCK_UNIT="$ROOT/systemd/user/maho-dock.service"
NOTIFY_UNIT="$ROOT/systemd/user/maho-notify.service"
CLIPBOARD_HISTORY_UNIT="$ROOT/systemd/user/maho-clipboard-history.service"
ADAPTIVE_UNIT="$ROOT/systemd/user/maho-adaptive.service"
SHELL_BIN="$ROOT/bin/maho-shell"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}

reject_text() {
    local file="$1" needle="$2" message="$3"
    if grep -Fq -- "$needle" "$file"; then
        fail "$message"
    fi
}

echo "=== Hyprland session ownership ==="
require_text "$HYPRLAND_LUA" 'require("maho.core.session")' \
    "Hyprland does not load the Maho session hook"
require_text "$SESSION_LUA" '-- managed-by: maho-setup session-v2' \
    "Hyprland session hook lost durable ownership marker"
require_text "$SESSION_LUA" 'hl.on("hyprland.start"' \
    "Hyprland start hook is missing"
require_text "$SESSION_LUA" 'hl.on("hyprland.shutdown"' \
    "Hyprland shutdown hook is missing"
require_text "$SESSION_LUA" '"$HOME/.local/bin/maho-session" start' \
    "Maho session start was removed"
require_text "$SESSION_LUA" '"$HOME/.local/bin/maho-session" stop' \
    "Maho session stop was removed"
reject_text "$SESSION_LUA" 'waybar' \
    "normal Hyprland startup still invokes Waybar"

require_text "$SHELL_BIN" 'restore_waybar()' \
    "emergency Waybar fallback was removed from Maho Shell"
require_text "$SHELL_BIN" 'trap restore_waybar EXIT INT TERM' \
    "Maho Shell crash fallback is no longer armed"
echo "PASS"

echo "=== durable session controller ==="
require_text "$SESSION_BIN" 'systemd_available()' \
    "systemd user-manager readiness check was dropped"
require_text "$SESSION_BIN" 'systemctl --user import-environment' \
    "graphical environment is not imported into the user manager"
require_text "$SESSION_BIN" 'wayland_ready()' \
    "Wayland socket readiness guard was dropped"
require_text "$SESSION_BIN" '[ -S "$runtime/$display" ]' \
    "Wayland readiness no longer verifies the compositor socket"
require_text "$SESSION_BIN" 'maho-awww-daemon.service' \
    "session controller no longer owns awww"
require_text "$SESSION_BIN" 'maho-dock.service' \
    "session controller no longer includes the accepted Dock runtime"
require_text "$SESSION_BIN" 'maho-clipboard-history.service' \
    "session controller no longer includes Clipboard history capture"
require_text "$SESSION_BIN" 'systemctl --user reset-failed' \
    "session controller no longer clears recoverable graphical failures"
require_text "$SESSION_BIN" 'systemctl --user start "$TARGET"' \
    "Maho session start no longer starts its target"
require_text "$SESSION_BIN" 'systemctl --user stop "$TARGET"' \
    "Maho session stop no longer stops its target"
require_text "$SESSION_BIN" 'systemctl --user unset-environment' \
    "session shutdown no longer clears graphical environment"
require_text "$SESSION_BIN" 'archive_hyprland_log' \
    "session shutdown no longer preserves compositor evidence"
require_text "$SESSION_BIN" 'tail -c 2097152 -- "$source"' \
    "compositor evidence is no longer bounded"
require_text "$SESSION_BIN" 'XDG_SESSION_DESKTOP' \
    "session desktop environment propagation was dropped"
require_text "$SESSION_BIN" 'wait-awww)' \
    "awww readiness command was dropped"
require_text "$SESSION_BIN" 'awww query' \
    "awww readiness command no longer probes the socket"
echo "PASS"

echo "=== failed-boot evidence survives the next login ==="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin" "$TMP/runtime/hypr/test-signature" "$TMP/state"
printf '%s\n' 'renderer probe from failed session' >"$TMP/runtime/hypr/test-signature/hyprland.log"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' >"$TMP/bin/systemctl"
chmod +x "$TMP/bin/systemctl"
PATH="$TMP/bin:$PATH" \
HOME="$TMP/home" \
XDG_RUNTIME_DIR="$TMP/runtime" \
XDG_STATE_HOME="$TMP/state" \
HYPRLAND_INSTANCE_SIGNATURE=test-signature \
    "$SESSION_BIN" stop
BOOT_ID="$(tr -d '\n' </proc/sys/kernel/random/boot_id)"
ARCHIVE="$TMP/state/maho/session/hyprland-$BOOT_ID.log"
[ -f "$ARCHIVE" ] || fail "Hyprland log was not preserved across session shutdown"
[ "$(stat -c '%a' "$ARCHIVE")" = 600 ] || fail "preserved Hyprland log is not private"
grep -Fq 'renderer probe from failed session' "$ARCHIVE" \
    || fail "preserved Hyprland log lost the compositor evidence"
echo "PASS"

echo "=== single graphical session target authority ==="
require_text "$TARGET" 'BindsTo=graphical-session.target' \
    "Maho session target no longer follows graphical-session lifetime"
require_text "$TARGET" 'After=graphical-session.target' \
    "Maho session target no longer waits for the graphical session"
for service in \
    maho-awww-daemon.service \
    maho-wallpaper.service \
    maho-shell.service \
    maho-dock.service \
    maho-notify.service \
    maho-clipboard-history.service \
    maho-adaptive.service; do
    require_text "$TARGET" "$service" \
        "$service is not pulled by the single Maho session target"
done
echo "PASS"

echo "=== graphical surface lifetime ==="
for unit in \
    "$AWWW_UNIT" \
    "$WALLPAPER_UNIT" \
    "$SHELL_UNIT" \
    "$DOCK_UNIT" \
    "$NOTIFY_UNIT" \
    "$CLIPBOARD_HISTORY_UNIT" \
    "$ADAPTIVE_UNIT"; do
    require_text "$unit" 'After=graphical-session.target' \
        "$(basename "$unit") lost graphical-session ordering"
    require_text "$unit" 'PartOf=maho-hyprland-session.target' \
        "$(basename "$unit") is not stopped with the Maho session target"
    require_text "$unit" 'ConditionEnvironment=WAYLAND_DISPLAY' \
        "$(basename "$unit") lost its Wayland gate"
    require_text "$unit" 'WantedBy=maho-hyprland-session.target' \
        "$(basename "$unit") can no longer be enabled under the Maho session target"
    reject_text "$unit" 'WantedBy=default.target' \
        "$(basename "$unit") regressed to user-manager default.target lifetime"
    reject_text "$unit" 'PartOf=graphical-session.target' \
        "$(basename "$unit") bypasses the Maho session lifetime authority"
done

require_text "$AWWW_UNIT" 'ExecStartPost=%h/.local/bin/maho-session wait-awww' \
    "awww service no longer waits for socket readiness"
require_text "$AWWW_UNIT" 'ExecStart=/usr/bin/awww-daemon --no-cache' \
    "awww service can replay an unrelated private cache at login"
require_text "$AWWW_UNIT" 'Restart=always' \
    "awww service cannot self-heal zero-status fatal exits"
require_text "$WALLPAPER_UNIT" 'Requires=maho-awww-daemon.service' \
    "wallpaper service no longer requires awww"
require_text "$SHELL_UNIT" 'SuccessExitStatus=143' \
    "Maho Shell clean termination contract regressed"
require_text "$DOCK_UNIT" 'ExecStart=%h/.local/bin/maho-dock run' \
    "Dock session service bypasses the accepted Dock launcher"
require_text "$NOTIFY_UNIT" 'ExecStart=%h/.local/bin/maho-notify run' \
    "Notify session service bypasses the accepted Notify launcher"
reject_text "$NOTIFY_UNIT" 'After=graphical-session.target maho-hyprland-session.target' \
    "Notify cannot order after its owning Maho session target"
require_text "$CLIPBOARD_HISTORY_UNIT" 'ExecStart=%h/.local/bin/maho-clipboard-history serve' \
    "Clipboard history service bypasses the accepted capture owner"
echo "PASS"

echo "=== syntax ==="
bash -n "$SESSION_BIN"
echo "PASS"

echo "ALL MAHO SESSION CONTRACTS PASS"
