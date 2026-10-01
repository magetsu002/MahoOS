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

maho_dashboard() {
    local cols
    local root
    local full
    local compact
    local tiny
    local metrics
    local full_w
    local compact_w
    local tiny_w
    local arch_logo_width=39
    local gap=2
    local full_logo_min compact_logo_min tiny_logo_min

    cols="${MAHO_DASHBOARD_COLUMNS:-$(tput cols 2>/dev/null || printf '80')}"
    root="$(maho_terminal_root)"
    full="$root/config/fastfetch/config.jsonc"
    compact="$root/config/fastfetch/config-narrow.jsonc"
    tiny="$root/config/fastfetch/config-tiny.jsonc"

    [[ -r "$full" && -r "$compact" && -r "$tiny" ]] || return 1

    metrics="$(maho_ff_metrics "$full")" || return 1
    full_w="${metrics%%$'\n'*}"

    metrics="$(maho_ff_metrics "$compact")" || return 1
    compact_w="${metrics%%$'\n'*}"

    metrics="$(maho_ff_metrics "$tiny")" || return 1
    tiny_w="${metrics%%$'\n'*}"

    full_logo_min=$(( full_w + gap + arch_logo_width ))
    compact_logo_min=$(( compact_w + gap + arch_logo_width ))
    tiny_logo_min=$(( tiny_w + gap + arch_logo_width ))

    if (( cols >= full_logo_min )); then
        maho_fastfetch --config "$full" --logo arch --logo-type builtin
    elif (( cols >= compact_logo_min )); then
        maho_fastfetch --config "$compact" --logo arch --logo-type builtin
    elif (( cols >= tiny_logo_min )); then
        maho_fastfetch --config "$tiny" --logo arch --logo-type builtin
    elif (( cols >= full_w )); then
        maho_fastfetch --config "$full" --logo none
    elif (( cols >= compact_w )); then
        maho_fastfetch --config "$compact" --logo none
    elif (( cols >= tiny_w )); then
        maho_fastfetch --config "$tiny" --logo none
    fi
}
