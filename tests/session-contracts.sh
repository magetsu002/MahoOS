#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SESSION_LUA="$ROOT/config/hypr/maho/core/session.lua"
HYPRLAND_LUA="$ROOT/config/hypr/hyprland.lua"
SESSION_BIN="$ROOT/bin/maho-session"
TARGET="$ROOT/systemd/user/maho-hyprland-session.target"
SHELL_UNIT="$ROOT/systemd/user/maho-shell.service"
NOTIFY_UNIT="$ROOT/systemd/user/maho-notify.service"
WALLPAPER_UNIT="$ROOT/systemd/user/maho-wallpaper.service"
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
require_text "$HYPRLAND_LUA" 'require("maho.core.session")' "Hyprland does not load the Maho session hook"
require_text "$SESSION_LUA" 'hl.on("hyprland.start"' "Hyprland start hook is missing"
require_text "$SESSION_LUA" 'hl.on("hyprland.shutdown"' "Hyprland shutdown hook is missing"
require_text "$SESSION_LUA" '"$HOME/.local/bin/maho-session" start' "Maho session start was removed"
require_text "$SESSION_LUA" '"$HOME/.local/bin/maho-session" stop' "Maho session stop was removed"
reject_text "$SESSION_LUA" 'waybar' "normal Hyprland startup still invokes Waybar"
require_text "$SHELL_BIN" 'restore_waybar()' "emergency Waybar fallback was removed from Maho Shell"
require_text "$SHELL_BIN" 'trap restore_waybar EXIT INT TERM' "Maho Shell crash fallback is no longer armed"
echo "PASS"

echo "=== graphical session target ==="
require_text "$TARGET" 'BindsTo=graphical-session.target' "Maho session target no longer binds to graphical-session.target"
require_text "$TARGET" 'Before=graphical-session.target' "Maho session target ordering changed"
require_text "$SESSION_BIN" 'systemctl --user import-environment' "Wayland environment is not imported into the user manager"
require_text "$SESSION_BIN" 'systemctl --user start "$TARGET"' "Maho session start no longer starts its target"
require_text "$SESSION_BIN" 'systemctl --user stop "$TARGET"' "Maho session stop no longer stops its target"
require_text "$SESSION_BIN" 'WAYLAND_DISPLAY' "Maho session no longer requires a Wayland environment"
echo "PASS"

echo "=== graphical surface units ==="
for unit in "$SHELL_UNIT" "$NOTIFY_UNIT" "$WALLPAPER_UNIT"; do
    require_text "$unit" 'After=graphical-session.target' "$(basename "$unit") lost graphical-session ordering"
    require_text "$unit" 'PartOf=graphical-session.target' "$(basename "$unit") lost graphical-session lifetime ownership"
    require_text "$unit" 'ConditionEnvironment=WAYLAND_DISPLAY' "$(basename "$unit") lost its Wayland gate"
    require_text "$unit" 'WantedBy=graphical-session.target' "$(basename "$unit") is not enabled through graphical-session.target"
    reject_text "$unit" 'WantedBy=default.target' "$(basename "$unit") regressed to default.target"
done
echo "PASS"

echo "=== syntax ==="
bash -n "$SESSION_BIN"
echo "PASS"

echo "ALL MAHO SESSION CONTRACTS PASS"
