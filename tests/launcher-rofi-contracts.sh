#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/bin/maho-launcher"
THEME="$ROOT/config/rofi/maho-launcher/launcher.rasi"
COMMANDS="$ROOT/config/rofi/maho-launcher/commands.sh"
GENERATOR="$ROOT/lib/maho_launcher_theme.py"
EDGE="$ROOT/config/quickshell/maho-shell/shell.qml"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

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

echo "=== mature engine and modes ==="
require_text "$LAUNCHER" 'command -v rofi' "production command does not require Rofi"
require_text "$LAUNCHER" '-show drun' "production Apps mode is not native drun"
require_text "$LAUNCHER" '-modes "drun,filebrowser,Commands:' "Apps/Files/Commands mode order changed"
require_text "$LAUNCHER" '-show-icons' "native desktop-entry icons are disabled"
require_text "$LAUNCHER" '-drun-display-format' "desktop-entry metadata format is missing"
reject_text "$LAUNCHER" 'quickshell' "production launcher still invokes Quickshell"
require_text "$COMMANDS" "case \"\${ROFI_INFO:-\${1:-}}\" in" "Commands mode lacks exact allowlist dispatch"
reject_text "$COMMANDS" 'eval ' "Commands mode exposes shell eval"
reject_text "$COMMANDS" 'bash -c' "Commands mode exposes arbitrary shell execution"
echo "PASS"

echo "=== Reference A visual and functional controls ==="
require_text "$THEME" 'content: "Maho Launcher"' "calm centered launcher title is missing"
require_text "$THEME" 'placeholder: "Search apps, files, and commands..."' "approved search copy changed"
require_text "$THEME" 'children: [ icon-app-grid, textbox-title, icon-settings ]' "functional header composition changed"
require_text "$THEME" 'action: "kb-clear-line"' "app-grid control no longer clears to the full list"
require_text "$THEME" 'action: "kb-mode-previous"' "settings control no longer opens the bounded Commands mode from Apps"
require_text "$THEME" 'action: "kb-page-next"' "Show more control is not functional"
require_text "$THEME" 'element selected.normal' "selected result slab styling is missing"
require_text "$THEME" 'icon-chevron' "result activation affordance is missing"
reject_text "$THEME" 'Enter to launch' "footer keyboard tutorial returned"
reject_text "$THEME" 'ESC to close' "footer keyboard tutorial returned"
reject_text "$THEME" '⌘' "macOS shortcut badges returned"
reject_text "$THEME" 'element-index' "number shortcut badges returned"
echo "PASS"

echo "=== Palette V2 and atomic generation ==="
require_text "$LAUNCHER" '/maho/theme/active.json' "active.json is not the palette authority"
require_text "$GENERATOR" 'NamedTemporaryFile' "theme generation is not staged"
require_text "$GENERATOR" 'os.fsync' "theme generation is not flushed before commit"
require_text "$GENERATOR" 'os.replace' "theme generation is not atomically committed"
require_text "$GENERATOR" 'maho-glass: rgba(14, 22, 33, 91%)' "neutral glass is no longer palette-independent"
require_text "$GENERATOR" 'maho-foreground:' "semantic foreground generation is missing"

for sample in monochrome cool warm saturated; do
    case "$sample" in
        monochrome) primary='#b9b9b9' ;;
        cool) primary='#80b7ff' ;;
        warm) primary='#ffb28d' ;;
        saturated) primary='#ff00d4' ;;
    esac
    mkdir -p "$TMP/$sample"
    printf '{"version":2,"mode":"dark","colors":{"primary":"%s","foreground":"#f2eeee","muted":"#c9bebe"}}\n' "$primary" > "$TMP/$sample/active.json"
    python3 "$GENERATOR" \
        --palette "$TMP/$sample/active.json" \
        --static-theme "$THEME" \
        --output-dir "$TMP/$sample/out"
    require_text "$TMP/$sample/out/generated-colors.rasi" 'maho-glass: rgba(14, 22, 33, 91%);' "$sample palette repainted the neutral glass"
done

cmp -s "$TMP/cool/out/generated-colors.rasi" "$TMP/warm/out/generated-colors.rasi" && fail "accent does not respond to palette changes"
echo "PASS"

echo "=== singleton, rollback, and Edge seam ==="
require_text "$LAUNCHER" 'flock -n 9' "single-instance lock is missing"
require_text "$LAUNCHER" '-pid "$ROFI_PID_FILE"' "Rofi instance pid isolation is missing"
require_text "$EDGE" '/.local/bin/maho-launcher' "Maho Edge does not call the production launcher"
require_text "$EDGE" '"open"' "Maho Edge does not use the bounded open command"
reject_text "$ROOT/bin/maho-setup" 'maho-rice-launcher' "setup now owns or removes the rollback launcher"
reject_text "$BINDS" 'maho-launcher' "global launcher keybind changed before approval"
echo "PASS"

echo "=== parser checks ==="
bash -n "$LAUNCHER" "$COMMANDS"
python3 -m py_compile "$GENERATOR"
if command -v rofi >/dev/null 2>&1; then
    XDG_CACHE_HOME="$TMP/cache" MAHO_ACTIVE_PALETTE="$TMP/cool/active.json" MAHO_ROOT="$ROOT" bash "$LAUNCHER" reload >/dev/null
    rofi -no-config -theme "$TMP/cache/maho/launcher/runtime-theme.rasi" -dump-theme >/dev/null
    echo "PASS  live Rasi parser"
else
    echo "INFO  Rofi unavailable; static and generator contracts passed"
fi

echo "ALL PRODUCTION ROFI LAUNCHER CONTRACTS PASS"
