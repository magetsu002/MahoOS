#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

[ -r "$BINDS" ] || fail "missing Maho Hyprland binds source"

grep -Fq -- '-- maho-clipboard-bind:begin' "$BINDS" \
    || fail "managed Clipboard bind marker missing"
grep -Fq -- 'mainMod .. " + V"' "$BINDS" \
    || fail "SUPER+V Clipboard binding missing"
grep -Fq -- 'hl.dsp.exec_cmd([["$HOME/.local/bin/maho-clipboard"]])' "$BINDS" \
    || fail "Clipboard binding does not route through managed runtime command"

if grep -Eq -- '/(Projects|home)/[^[:space:]]*Maho-OS/bin/maho-clipboard|/Projects/Maho-OS/bin/maho-clipboard' "$BINDS"; then
    fail "Clipboard binding still contains a source-tree path"
fi

printf 'PASS  SUPER+V routes through managed Maho Clipboard command\n'
