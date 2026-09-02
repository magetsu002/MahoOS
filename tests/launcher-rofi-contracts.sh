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
require_text "$LAUNCHER" '-show "$initial_mode"' "production launcher cannot intentionally reopen a requested native mode"
require_text "$LAUNCHER" '-modes "drun,filebrowser,Commands:' "Apps/Files/Commands mode order changed"
require_text "$LAUNCHER" '-show-icons' "native desktop-entry icons are disabled"
require_text "$LAUNCHER" '-drun-display-format' "desktop-entry metadata format is missing"
reject_text "$LAUNCHER" 'quickshell' "production launcher still invokes Quickshell"
require_text "$COMMANDS" "case \"\${ROFI_INFO:-\${1:-}}\" in" "Commands mode lacks exact allowlist dispatch"
reject_text "$COMMANDS" 'eval ' "Commands mode exposes shell eval"
reject_text "$COMMANDS" 'bash -c' "Commands mode exposes arbitrary shell execution"
echo "PASS"

echo "=== approved target composition and functional chrome ==="
require_text "$THEME" 'content: "Maho Launcher"' "centered launcher title is missing"
require_text "$THEME" 'placeholder: "Search apps, files, and commands..."' "approved search copy changed"
require_text "$THEME" 'children: [ icon-app-grid, textbox-title, icon-settings ]' "functional header composition changed"
require_text "$THEME" 'action: "kb-custom-1"' "app-grid control is no longer a bounded Apps action"
require_text "$THEME" 'action: "kb-custom-2"' "settings control is no longer a bounded Commands action"
require_text "$LAUNCHER" "-kb-custom-1 'F13'" "Apps header action lost its isolated Rofi custom binding"
require_text "$LAUNCHER" "-kb-custom-2 'F14'" "Commands header action lost its isolated Rofi custom binding"
require_text "$LAUNCHER" '10)' "Apps header custom return code is not handled"
require_text "$LAUNCHER" 'mode="drun"' "Apps header action no longer returns to native drun"
require_text "$LAUNCHER" '11)' "Commands header custom return code is not handled"
require_text "$LAUNCHER" 'mode="Commands"' "settings header action no longer opens bounded Commands"
require_text "$THEME" 'action: "kb-page-next"' "Show more control is not functional"

require_text "$THEME" 'width: 760px' "approved near-square launcher width changed"
reject_text "$THEME" 'height: 730px' "fixed window height returned; sparse result sets will produce a dead slab"
require_text "$THEME" 'border-radius: 24px' "outer radius drifted from the current Maho surface grammar"
require_text "$THEME" 'spacing: 12px' "major groups no longer match the refined density"
require_text "$THEME" 'font: "Inter 10"' "launcher typography is oversized again"
require_text "$THEME" 'lines: 9' "approved visible result density changed"
require_text "$THEME" 'padding: 7px 12px' "result-row density drifted from the refined target"
require_text "$THEME" 'size: 28px' "application icon scale drifted from the refined target"
require_text "$THEME" 'background-image: @maho-control-material' "header utility controls lost their layered glass hit-target material"
require_text "$THEME" 'border-color: @maho-control-rim' "header utility controls lost their restrained rim"
require_text "$THEME" 'fixed-height: false' "sparse result sets again reserve empty launcher space"
require_text "$THEME" 'dynamic: true' "filtered result sets no longer resize naturally"
require_text "$THEME" 'tint: @maho-icon-muted' "symbolic chrome is no longer intentionally subdued"
require_text "$THEME" 'background-image: @maho-active-mode-material' "selected segment is no longer a lifted tinted material"
require_text "$THEME" 'background-image: @maho-selection-material' "selected result is no longer a filled glass state"
require_text "$THEME" 'border-color: @maho-result-rim' "results region lost its quiet shared-container rim"
reject_text "$THEME" 'Enter to launch' "footer keyboard tutorial returned"
reject_text "$THEME" 'ESC to close' "footer keyboard tutorial returned"
reject_text "$THEME" '⌘' "macOS shortcut badges returned"
reject_text "$THEME" 'element-index' "number shortcut badges returned"
echo "PASS"

echo "=== shared Maho Palette V2 material ==="
require_text "$LAUNCHER" '/maho/theme/active.json' "active.json is not the palette authority"
require_text "$GENERATOR" 'NamedTemporaryFile' "theme generation is not staged"
require_text "$GENERATOR" 'os.fsync' "theme generation is not flushed before commit"
require_text "$GENERATOR" 'os.replace' "theme generation is not atomically committed"
require_text "$GENERATOR" 'blend(surface_high, background, 0.28)' "launcher shell no longer mirrors Maho Link semantic shell mixing"
require_text "$GENERATOR" 'blend(surface_high, background, 0.36)' "launcher insets no longer mirror Maho Link semantic inset mixing"
require_text "$GENERATOR" 'current_saturation < 0.08' "stable low-chroma accent handling is missing"
require_text "$GENERATOR" 'maho-control-material:' "layered header control material token is missing"
require_text "$GENERATOR" 'maho-result-rim:' "results-region material token is missing"
require_text "$GENERATOR" 'maho-muted-soft:' "secondary-text hierarchy token is missing"
require_text "$GENERATOR" 'neutral = (18, 18, 20)' "Maho iOS graphite glass foundation is missing"
reject_text "$GENERATOR" 'neutralize(' "launcher-specific palette desaturation returned"

for sample in monochrome cool warm pink green; do
    case "$sample" in
        monochrome) background='#111111'; surface='#242424'; surface_high='#323232'; primary='#b9b9b9'; foreground='#f2f2f2'; muted='#c4c4c4'; outline='#888888' ;;
        cool) background='#0b1524'; surface='#17283b'; surface_high='#263b53'; primary='#80b7ff'; foreground='#f1f5fb'; muted='#b4bfce'; outline='#778899' ;;
        warm) background='#1d120c'; surface='#2b1e18'; surface_high='#392a22'; primary='#ff9b6c'; foreground='#f6eee9'; muted='#cbb9af'; outline='#8e7a70' ;;
        pink) background='#180f18'; surface='#281c28'; surface_high='#372737'; primary='#e989d8'; foreground='#f6eff5'; muted='#c9b8c6'; outline='#917f8e' ;;
        green) background='#11150c'; surface='#202719'; surface_high='#2d3723'; primary='#a9b96d'; foreground='#f0f3e9'; muted='#b9c0ad'; outline='#7d866e' ;;
    esac

    mkdir -p "$TMP/$sample"
    printf '{"version":2,"mode":"dark","colors":{"background":"%s","surface_container":"%s","surface_container_high":"%s","primary":"%s","foreground":"%s","muted":"%s","outline":"%s"}}\n' \
        "$background" "$surface" "$surface_high" "$primary" "$foreground" "$muted" "$outline" > "$TMP/$sample/active.json"

    python3 "$GENERATOR" \
        --palette "$TMP/$sample/active.json" \
        --static-theme "$THEME" \
        --output-dir "$TMP/$sample/out"

    require_text "$TMP/$sample/out/generated-colors.rasi" 'maho-accent-soft:' "$sample palette lacks a selected-segment material"
    require_text "$TMP/$sample/out/generated-colors.rasi" 'maho-selection:' "$sample palette lacks a selected-row material"
done

python3 - "$TMP" <<'PY'
from pathlib import Path
import math
import re
import sys

root = Path(sys.argv[1])

def token(sample, name):
    text = (root / sample / "out" / "generated-colors.rasi").read_text()
    match = re.search(rf"{name}: rgba\((\d+), (\d+), (\d+), (\d+)%\);", text)
    if not match:
        raise SystemExit(f"missing {name} for {sample}")
    return tuple(map(int, match.groups()))

def effective_alpha(base_percent, layer_percent):
    base = base_percent / 100
    layer = layer_percent / 100
    return base + (1 - base) * layer

samples = ("monochrome", "cool", "warm", "pink", "green")
panels = {sample: token(sample, "maho-glass") for sample in samples}
selections = {sample: token(sample, "maho-selection") for sample in samples}

if not all(68 <= value[3] <= 76 for value in panels.values()):
    raise SystemExit("outer material escaped the frosted Maho iOS opacity envelope")

if max(panels["monochrome"][:3]) - min(panels["monochrome"][:3]) > 6:
    raise SystemExit("monochrome palette produced a synthetic chromatic shell")

if len({value[:3] for value in panels.values()}) < 4:
    raise SystemExit("launcher shell no longer responds to Palette V2 family changes")

panel_distance = math.dist(panels["cool"][:3], panels["warm"][:3])
selection_distance = math.dist(selections["cool"][:3], selections["warm"][:3])

if not 2 <= panel_distance <= 16:
    raise SystemExit("shell tint must stay subtle while still reacting to the environment")

if selection_distance <= panel_distance * 2.5:
    raise SystemExit("selected state does not carry substantially more accent separation than the shell")

for sample in samples:
    panel_alpha = panels[sample][3]
    for name, floor, ceiling in (
        ("maho-inset", 0.74, 0.78),
        ("maho-segment", 0.73, 0.76),
        ("maho-result-surface", 0.72, 0.75),
        ("maho-selection", 0.79, 0.83),
    ):
        combined = effective_alpha(panel_alpha, token(sample, name)[3])
        if not floor <= combined <= ceiling:
            raise SystemExit(
                f"{sample} {name} effective alpha {combined:.3f} escaped {floor:.2f}-{ceiling:.2f}"
            )
PY
echo "PASS"

echo "=== singleton, rollback, and Edge seam ==="
require_text "$LAUNCHER" 'flock -n 9' "single-instance lock is missing"
require_text "$LAUNCHER" '-pid "$ROFI_PID_FILE"' "Rofi instance pid isolation is missing"
require_text "$LAUNCHER" 'ignore_alpha = 0.06' "launcher blur coverage is no longer tuned for translucent material"
require_text "$LAUNCHER" 'xray = true' "launcher blur can no longer sample the full backdrop"
reject_text "$LAUNCHER" 'hl.config({' "launcher performs a persistent/global Hyprland mutation"
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
    parser_err="$TMP/rofi-parser.err"
    if rofi -no-config -theme "$TMP/cache/maho/launcher/runtime-theme.rasi" -dump-theme >/dev/null 2>"$parser_err" \
        && ! grep -Fq 'Failed to parse theme' "$parser_err"; then
        echo "PASS  live Rasi parser"
    else
        cat "$parser_err" >&2
        fail "generated runtime theme does not parse"
    fi
else
    echo "INFO  Rofi unavailable; static and generator contracts passed"
fi

echo "ALL PRODUCTION ROFI LAUNCHER CONTRACTS PASS"
