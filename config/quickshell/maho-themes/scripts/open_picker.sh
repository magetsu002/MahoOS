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

mkdir -p "$STATE_DIR"

if [ "${1:-}" = "--lock-held" ]; then
    ensure_wallpaper_cache_compatibility
    mkdir -p "$WALLPAPER_DIR"
    "$SCRIPT_DIR/sync_thumbs.sh" "$WALLPAPER_DIR"
    exec quickshell --no-duplicate -p "$PROJECT_DIR/shell.qml"
fi

if command -v flock >/dev/null 2>&1; then
    exec flock -n -o \
        "$STATE_DIR/ui.lock" \
        bash "$0" --lock-held
fi

ensure_wallpaper_cache_compatibility
mkdir -p "$WALLPAPER_DIR"
"$SCRIPT_DIR/sync_thumbs.sh" "$WALLPAPER_DIR"
exec quickshell --no-duplicate -p "$PROJECT_DIR/shell.qml"
