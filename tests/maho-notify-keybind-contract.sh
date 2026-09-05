#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

[ -r "$BINDS" ] || fail "missing binds: $BINDS"

[ "$(grep -Fxc -- '-- maho-notify-bind:begin' "$BINDS" || true)" -eq 1 ] \
    || fail 'managed notification bind begin marker missing or duplicated'

[ "$(grep -Fxc -- '-- maho-notify-bind:end' "$BINDS" || true)" -eq 1 ] \
    || fail 'managed notification bind end marker missing or duplicated'

grep -Fq 'mainMod .. " + SHIFT + N"' "$BINDS" \
    || fail 'SUPER+SHIFT+N notification center binding missing'

grep -Fq '"$HOME/.local/bin/maho-notify" center' "$BINDS" \
    || fail 'notification keybind does not invoke Maho Notify center'

if grep -Fq 'mainMod .. " + N"' "$BINDS"; then
    fail 'legacy SUPER+N notification binding returned'
fi

[ "$(grep -Fc 'mainMod .. " + SHIFT + N"' "$BINDS")" -eq 1 ] \
    || fail 'SUPER+SHIFT+N notification binding duplicated'

echo 'PASS: SUPER+SHIFT+N notification center binding contract'
