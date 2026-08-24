#!/usr/bin/env bash

set -u

wallpaper_cache_home() {
    printf '%s\n' "${XDG_CACHE_HOME:-$HOME/.cache}"
}

wallpaper_cache_dir() {
    printf '%s/maho/themes\n' "$(wallpaper_cache_home)"
}

legacy_wallpaper_cache_dir() {
    printf '%s/.cache/wallpaper_picker\n' "$HOME"
}

ensure_wallpaper_cache_compatibility() {
    local cache_dir legacy_dir
    cache_dir="$(wallpaper_cache_dir)"
    legacy_dir="$(legacy_wallpaper_cache_dir)"

    mkdir -p "$cache_dir"

    # Seed reusable thumbnails without moving or modifying the old picker's
    # rollback cache. Maho Themes owns all subsequent writes under maho/themes.
    if [[ "$cache_dir" != "$legacy_dir" && -d "$legacy_dir" ]]; then
        cp -a -n -- "$legacy_dir/." "$cache_dir/"
    fi
}
