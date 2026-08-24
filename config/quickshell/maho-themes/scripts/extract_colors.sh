#!/usr/bin/env bash

set -euo pipefail

CACHE_DIR="${1:-}"
[ -n "$CACHE_DIR" ] || {
    echo "Maho Themes color cache path is required" >&2
    exit 2
}

COLOR_DIR="$CACHE_DIR/colors_markers"
THUMBS="$CACHE_DIR/thumbs"
CSV="$CACHE_DIR/colors.csv"

mkdir -p "$COLOR_DIR"
[ -d "$THUMBS" ] || exit 0

if [ -f "$CSV" ]; then
    while IFS=, read -r fname hexcode; do
        cleanhex="$(printf '%s' "$hexcode" | tr -d '\r#' | cut -c 1-6)"
        if [[ "$cleanhex" =~ ^[0-9A-Fa-f]{6}$ ]] && [ -n "$fname" ]; then
            touch -- "$COLOR_DIR/${fname}_HEX_${cleanhex}"
        fi
    done < "$CSV"
    mv -- "$CSV" "$CSV.bak"
fi

if command -v magick >/dev/null 2>&1; then
    IMAGE_COMMAND=magick
elif command -v convert >/dev/null 2>&1; then
    IMAGE_COMMAND=convert
else
    exit 0
fi

find "$THUMBS" -maxdepth 1 -type f -print0 |
while IFS= read -r -d '' file; do
    filename="$(basename -- "$file")"
    if find "$COLOR_DIR" -maxdepth 1 -type f \
        -name "${filename}_HEX_*" -print -quit | grep -q .
    then
        continue
    fi

    hex="$("$IMAGE_COMMAND" "$file" \
        -modulate 100,200 \
        -resize '1x1^' \
        -gravity center \
        -extent 1x1 \
        -depth 8 \
        -format '%[hex:p{0,0}]' \
        info:- 2>/dev/null | grep -oE '[0-9A-Fa-f]{6}' | head -n 1 || true)"

    if [[ "$hex" =~ ^[0-9A-Fa-f]{6}$ ]]; then
        touch -- "$COLOR_DIR/${filename}_HEX_${hex}"
    fi
done
