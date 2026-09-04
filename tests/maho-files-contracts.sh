#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WRAPPER="$ROOT/bin/maho-files"
RENDERER="$ROOT/lib/maho_files_theme.py"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

pass() {
    echo "PASS: $*"
}

[ -r "$WRAPPER" ] || fail "maho-files wrapper missing"
[ -r "$RENDERER" ] || fail "Maho Files GTK renderer missing"

bash -n "$WRAPPER"
python -m py_compile "$RENDERER" "$ROOT/tests/test_maho_files_theme.py"
pass "wrapper and renderer syntax"

# Maho Files must remain presentation-only. Thunar owns filesystem semantics.
grep -Fq 'GTK_THEME="$THEME_NAME"' "$WRAPPER" || fail "private GTK_THEME boundary missing"
grep -Fq 'exec thunar' "$WRAPPER" || fail "foreground path must execute real Thunar"
grep -Fq 'thunar --quit' "$WRAPPER" || fail "explicit restart/quit authority missing"

if grep -Eq '(^|[^[:alnum:]_])(rm|mv|cp)[[:space:]]' "$WRAPPER"; then
    fail "wrapper must not implement file operations"
fi

if grep -Eq '\.config/gtk-3\.0/gtk\.css|XDG_CONFIG_HOME=.*maho-files' "$WRAPPER" "$RENDERER"; then
    fail "Maho Files must not overwrite or replace global GTK configuration"
fi

if grep -Eq 'tracker|baloo|recoll|find[[:space:]].*-type|inotifywait' "$WRAPPER"; then
    fail "V1 must not add a parallel file indexer or watcher"
fi
pass "Thunar remains sole file-management engine"

# Existing vanilla Thunar windows may not be killed by a normal launch.
python - "$WRAPPER" <<'PY'
from pathlib import Path
import sys
text=Path(sys.argv[1]).read_text()
normal=text.split('restart_thunar() {', 1)[0]
if 'thunar --quit' in normal:
    raise SystemExit('normal launch path may not terminate Thunar')
PY
pass "normal launches preserve existing Thunar windows"

# Material must be compositional glass, not whole-window opacity.
grep -Fq 'background-color: alpha(@maho_bg, 0.62)' "$RENDERER" || fail "translucent window material missing"
grep -Fq 'placessidebar' "$RENDERER" || fail "native Places sidebar styling missing"
grep -Fq 'treeview.view' "$RENDERER" || fail "native detailed list styling missing"
grep -Fq 'iconview.view' "$RENDERER" || fail "native icon view styling missing"
grep -Fq 'button.titlebutton.close:hover' "$RENDERER" || fail "premium real close-button styling missing"

if grep -Eq 'opacity:[[:space:]]*0\.[0-9]+' "$RENDERER"; then
    fail "do not fade the whole GTK window; use alpha surfaces so text/icons stay opaque"
fi
pass "glass hierarchy and premium close contract"

# Wallpaper color authority stays with Maho palette; no red target hardcoding.
if grep -Eqi '#(ff0000|ff0033|e6002d|d00020)|rgb\([^)]*255[^)]*,[^)]*0[^)]*,[^)]*0' "$RENDERER"; then
    fail "wallpaper-specific red must not be hardcoded into Maho Files"
fi
grep -Fq 'data.get("semantic")' "$RENDERER" || fail "Palette V2 semantic roles must be consumed"
grep -Fq 'data.get("colors")' "$RENDERER" || fail "legacy palette fallback must remain supported"
pass "Palette V2 authority with legacy compatibility"

echo "ALL MAHO FILES M1 CONTRACTS PASS"
