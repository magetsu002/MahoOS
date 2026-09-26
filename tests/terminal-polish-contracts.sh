#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DASH="$ROOT/config/zshrc/maho-dashboard.zsh"
KITTY="$ROOT/config/kitty/maho.conf"
THEME="$ROOT/bin/maho-theme"
SETUP="$ROOT/bin/maho-setup"
INSTALL="$ROOT/bin/maho-terminal-install"

fail() { echo "FAIL $*" >&2; exit 1; }
pass() { echo "PASS $*"; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject_text() { ! grep -Fq -- "$2" "$1" || fail "$3"; }

python "$ROOT/tests/test_terminal_theme.py"

require_text "$DASH" '--logo-type kitty-icat' "dashboard no longer delegates image layout to Fastfetch"
reject_text "$DASH" '28x18@-4x3' "legacy negative icat placement remains"
reject_text "$DASH" '\033[3A' "legacy cursor rewind remains"
reject_text "$DASH" 'script -qfec' "legacy PTY capture path remains"
reject_text "$DASH" 'sed "s/^/' "legacy fake indentation remains"
require_text "$DASH" 'MAHO_DASHBOARD_COLUMNS' "dashboard width contract is not testable"
pass "dashboard has one measured Fastfetch-native layout path"

require_text "$KITTY" 'include ~/.cache/maho/theme/kitty.conf' "Kitty does not consume generated Maho palette"
reject_text "$KITTY" 'current-theme.conf' "stale static Kitty theme remains authoritative"
pass "Kitty include points only at generated Palette V2 output"

require_text "$THEME" 'maho-terminal-theme" render "$canonical" "$txn/kitty.conf"' "terminal palette is not generated inside theme transaction"
require_text "$THEME" 'candidate-kitty.conf' "generated Kitty candidate is not transactionally staged"
require_text "$THEME" 'maho-terminal-theme" reload' "Kitty live reload is not wired"
pass "theme transaction stages and publishes terminal palette"

require_text "$SETUP" 'maho-terminal-dashboard maho-terminal-theme maho-terminal-install' "terminal commands are not runtime-owned"
require_text "$SETUP" 'maho-terminal-install")" install' "terminal config is not deployed by runtime setup"
require_text "$SETUP" 'TERMINAL_KITTY_CONFIG' "Kitty root config is not rollback-snapshotted"
pass "runtime setup owns terminal wiring narrowly"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/config" "$TMP/cache"
HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/config" XDG_CACHE_HOME="$TMP/cache" MAHO_ROOT="$ROOT" bash "$INSTALL" install
HOME="$TMP/home" XDG_CONFIG_HOME="$TMP/config" XDG_CACHE_HOME="$TMP/cache" MAHO_ROOT="$ROOT" bash "$INSTALL" verify
grep -Fq '# BEGIN_MAHO_THEME' "$TMP/config/kitty/kitty.conf" || fail "fresh Kitty config missing Maho block"
grep -Fq 'include maho.conf' "$TMP/config/kitty/kitty.conf" || fail "fresh Kitty config missing narrow include"
pass "fresh terminal install is reproducible without replacing unrelated config"

echo "=== terminal palette generation failure is fail-safe ==="
FAILROOT="$TMP/fail-root"
FAILCACHE="$TMP/fail-cache"
mkdir -p "$FAILROOT/theme" "$FAILROOT/bin" "$FAILCACHE/maho/theme"
cp "$ROOT/theme/palette_v2.py" "$FAILROOT/theme/palette_v2.py"
cat >"$FAILROOT/bin/maho-terminal-theme" <<'EOF_FAIL_TERMINAL'
#!/usr/bin/env bash
exit 77
EOF_FAIL_TERMINAL
chmod +x "$FAILROOT/bin/maho-terminal-theme"
cat >"$TMP/backend" <<'EOF_BACKEND'
#!/usr/bin/env bash
cat >"$3" <<'EOF_RAW'
{
  "background":"#141218","surface":"#18161c","surface_container":"#211f26",
  "surface_container_high":"#2b2930","foreground":"#e6e1e5","muted":"#cac4d0",
  "primary":"#d0bcff","on_primary":"#381e72","secondary":"#ccc2dc",
  "on_secondary":"#332d41","tertiary":"#efb8c8","on_tertiary":"#492532",
  "error":"#f2b8b5","on_error":"#601410","outline":"#938f99",
  "outline_variant":"#49454f"
}
EOF_RAW
EOF_BACKEND
chmod +x "$TMP/backend"
cat >"$TMP/wall.ppm" <<'EOF_PPM'
P3
2 2
255
12 14 18  50 55 60
120 100 80  220 200 180
EOF_PPM
printf '%s\n' '{"sentinel":"keep-active"}' >"$FAILCACHE/maho/theme/active.json"
before="$(sha256sum "$FAILCACHE/maho/theme/active.json")"
if MAHO_ROOT="$FAILROOT" XDG_CACHE_HOME="$FAILCACHE" MAHO_THEME_BACKEND="$TMP/backend"     bash "$THEME" apply "$TMP/wall.ppm" dark >/dev/null 2>&1
then
    fail "theme apply succeeded despite terminal palette generator failure"
fi
after="$(sha256sum "$FAILCACHE/maho/theme/active.json")"
[ "$before" = "$after" ] || fail "terminal palette generation failure corrupted active theme"
pass "terminal palette generation failure leaves active theme unchanged"

echo "ALL TERMINAL POLISH CONTRACTS PASS"
