#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &&
    pwd
)"
PROJECT_DIR="$(
    cd -- "$SCRIPT_DIR/.." &&
    pwd
)"

# shellcheck source=cache_paths.sh
source "$SCRIPT_DIR/cache_paths.sh"

WALLPAPER_DIR="${QS_WALLPAPER_DIR:-$HOME/Wallpapers}"
STATE_DIR="$(wallpaper_cache_dir)"
PICKER_PATH="$PROJECT_DIR/shell.qml"

restore_super_q() {
    hyprctl repl \
        'hl.unbind("SUPER + Q"); hl.bind("SUPER + Q", hl.dsp.window.close())' \
        >/dev/null 2>&1 || true
}

run_picker() {
    if [ "${MAHO_THEMES_MANAGE_SUPER_Q:-0}" != 1 ] ||
       ! command -v hyprctl >/dev/null 2>&1 ||
       [ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]
    then
        exec quickshell --no-duplicate -p "$PICKER_PATH"
    fi

    local close_command lua_close_command
    printf -v close_command 'quickshell kill -p %q' "$PICKER_PATH"
    lua_close_command="$(
        python -c 'import json, sys; print(json.dumps(sys.argv[1]))' \
            "$close_command"
    )"

    if ! hyprctl repl \
        "hl.unbind(\"SUPER + Q\"); hl.bind(\"SUPER + Q\", hl.dsp.exec_cmd($lua_close_command))" \
        >/dev/null
    then
        exec quickshell --no-duplicate -p "$PICKER_PATH"
    fi

    trap restore_super_q EXIT
    quickshell --no-duplicate -p "$PICKER_PATH"
}

mkdir -p "$STATE_DIR"

if [ "${1:-}" = "--lock-held" ]; then
    ensure_wallpaper_cache_compatibility
    mkdir -p "$WALLPAPER_DIR"
    "$SCRIPT_DIR/sync_thumbs.sh" "$WALLPAPER_DIR"
    run_picker
    exit $?
fi

if command -v flock >/dev/null 2>&1; then
    exec flock -n -o \
        "$STATE_DIR/ui.lock" \
        bash "$0" --lock-held
fi

ensure_wallpaper_cache_compatibility
mkdir -p "$WALLPAPER_DIR"
"$SCRIPT_DIR/sync_thumbs.sh" "$WALLPAPER_DIR"
run_picker
