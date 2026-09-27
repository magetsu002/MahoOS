# managed-by: maho-terminal v1

maho_terminal_root() {
    printf '%s\n' "${MAHO_ROOT:-${XDG_DATA_HOME:-$HOME/.local/share}/maho/runtime/current}"
}

maho_fastfetch() {
    "${MAHO_FASTFETCH_BIN:-/usr/bin/fastfetch}" "$@"
}

maho_ff_metrics() {
    local cfg="$1"
    local probe
    probe="$(mktemp)"

    if ! COLUMNS=500 maho_fastfetch --config "$cfg" --logo none --pipe > "$probe" 2>/dev/null; then
        rm -f "$probe"
        return 1
    fi

    python - "$probe" <<'PY_METRICS'
from pathlib import Path
import sys
import unicodedata

def width(s):
    result = 0
    for ch in s.rstrip("\n"):
        if unicodedata.combining(ch):
            continue
        if unicodedata.category(ch) in ("Cc", "Cf"):
            continue
        result += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return result

lines = Path(sys.argv[1]).read_text(errors="replace").splitlines()
print(max((width(line) for line in lines), default=0))
print(len(lines))
PY_METRICS

    rm -f "$probe"
}

maho_native_dashboard() {
    local cfg="$1"
    local card_width="$2"
    local rows="$3"
    local cols="$4"
    local max_logo="$5"
    local img="$6"
    local gap=2
    local min_logo=7
    local available=$(( cols - card_width - gap ))
    local imgw
    local imgh
    local top

    if (( available < min_logo )); then
        /usr/bin/fastfetch --config "$cfg" --logo none
        return
    fi

    imgw="$available"
    (( imgw > max_logo )) && imgw="$max_logo"
    imgh=$(( (imgw * 215 + 130) / 260 ))
    (( imgh < 6 )) && imgh=6
    top=$(( (rows - imgh) / 2 ))
    (( top < 0 )) && top=0

    maho_fastfetch \
        --config "$cfg" \
        --logo "$img" \
        --logo-type kitty-icat \
        --logo-width "$imgw" \
        --logo-height "$imgh" \
        --logo-padding-right "$gap" \
        --logo-padding-top "$top"
}

maho_dashboard() {
    local cols
    local root
    local img
    local full
    local compact
    local tiny
    local metrics
    local full_w full_rows
    local compact_w compact_rows
    local tiny_w tiny_rows
    local full_logo_min compact_logo_min tiny_logo_min
    local image_ok=0

    cols="${MAHO_DASHBOARD_COLUMNS:-$(tput cols 2>/dev/null || printf '80')}"
    root="$(maho_terminal_root)"
    img="$root/share/maho/terminal/kurisu-transparent.apng"
    full="$root/config/fastfetch/config.jsonc"
    compact="$root/config/fastfetch/config-narrow.jsonc"
    tiny="$root/config/fastfetch/config-tiny.jsonc"

    [[ -r "$full" && -r "$compact" && -r "$tiny" ]] || return 1

    metrics="$(maho_ff_metrics "$full")" || return 1
    full_w="${metrics%%$'\n'*}"
    full_rows="${metrics##*$'\n'}"

    metrics="$(maho_ff_metrics "$compact")" || return 1
    compact_w="${metrics%%$'\n'*}"
    compact_rows="${metrics##*$'\n'}"

    metrics="$(maho_ff_metrics "$tiny")" || return 1
    tiny_w="${metrics%%$'\n'*}"
    tiny_rows="${metrics##*$'\n'}"

    full_logo_min=$(( full_w + 2 + 7 ))
    compact_logo_min=$(( compact_w + 2 + 7 ))
    tiny_logo_min=$(( tiny_w + 2 + 7 ))

    if [[ -n "${KITTY_WINDOW_ID:-}" && -r "$img" && "${MAHO_DASHBOARD_NO_IMAGE:-0}" != 1 ]]; then
        image_ok=1
    fi

    if (( image_ok && cols >= full_logo_min )); then
        maho_native_dashboard "$full" "$full_w" "$full_rows" "$cols" 16 "$img"
    elif (( image_ok && cols >= compact_logo_min )); then
        maho_native_dashboard "$compact" "$compact_w" "$compact_rows" "$cols" 14 "$img"
    elif (( image_ok && cols >= tiny_logo_min )); then
        maho_native_dashboard "$tiny" "$tiny_w" "$tiny_rows" "$cols" 12 "$img"
    elif (( cols >= full_w )); then
        /usr/bin/fastfetch --config "$full" --logo none
    elif (( cols >= compact_w )); then
        /usr/bin/fastfetch --config "$compact" --logo none
    elif (( cols >= tiny_w )); then
        /usr/bin/fastfetch --config "$tiny" --logo none
    fi
}
