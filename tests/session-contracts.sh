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
NOTIFY_UNIT="$ROOT/systemd/user/maho-notify.service"
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
require_text "$SESSION_BIN" 'systemctl --user reset-failed' \
    "session controller no longer clears recoverable graphical failures"
require_text "$SESSION_BIN" 'systemctl --user start "$TARGET"' \
    "Maho session start no longer starts its target"
require_text "$SESSION_BIN" 'systemctl --user stop "$TARGET"' \
    "Maho session stop no longer stops its target"
require_text "$SESSION_BIN" 'systemctl --user unset-environment' \
    "session shutdown no longer clears graphical environment"
require_text "$SESSION_BIN" 'XDG_SESSION_DESKTOP' \
    "session desktop environment propagation was dropped"
require_text "$SESSION_BIN" 'wait-awww)' \
    "awww readiness command was dropped"
require_text "$SESSION_BIN" 'awww query' \
    "awww readiness command no longer probes the socket"
echo "PASS"

echo "=== graphical session target ==="
require_text "$TARGET" 'BindsTo=graphical-session.target' \
    "Maho session target no longer binds to graphical-session.target"
require_text "$TARGET" 'Before=graphical-session.target' \
    "Maho session target ordering changed"
echo "PASS"

echo "=== graphical surface units ==="
for unit in "$AWWW_UNIT" "$WALLPAPER_UNIT" "$SHELL_UNIT" "$NOTIFY_UNIT"; do
    require_text "$unit" 'After=graphical-session.target' \
        "$(basename "$unit") lost graphical-session ordering"
    require_text "$unit" 'PartOf=graphical-session.target' \
        "$(basename "$unit") lost graphical-session lifetime ownership"
    require_text "$unit" 'ConditionEnvironment=WAYLAND_DISPLAY' \
        "$(basename "$unit") lost its Wayland gate"
    require_text "$unit" 'WantedBy=graphical-session.target' \
        "$(basename "$unit") is not enabled through graphical-session.target"
    reject_text "$unit" 'WantedBy=default.target' \
        "$(basename "$unit") regressed to default.target"
done

require_text "$AWWW_UNIT" 'ExecStartPost=%h/.local/bin/maho-session wait-awww' \
    "awww service no longer waits for socket readiness"
require_text "$WALLPAPER_UNIT" 'After=graphical-session.target maho-awww-daemon.service' \
    "wallpaper service lost awww ordering"
require_text "$WALLPAPER_UNIT" 'Requires=maho-awww-daemon.service' \
    "wallpaper service no longer requires awww"
require_text "$SHELL_UNIT" 'SuccessExitStatus=143' \
    "Maho Shell clean termination contract regressed"
echo "PASS"

echo "=== syntax ==="
bash -n "$SESSION_BIN"
bash -n "$ROOT/bin/maho-setup"
echo "PASS"

echo "ALL MAHO SESSION CONTRACTS PASS"
