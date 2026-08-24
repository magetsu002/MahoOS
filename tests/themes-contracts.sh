#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
THEMES="$ROOT/config/quickshell/maho-themes"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "=== Maho Themes product and entrypoint ==="
[ -r "$THEMES/shell.qml" ] || fail "shell.qml entrypoint missing"
grep -Fq 'title: "Maho Themes"' "$THEMES/shell.qml" || fail "window title is not Maho Themes"
grep -Fq 'text: "Maho Themes"' "$THEMES/WallpaperPicker.qml" || fail "visible product name missing"
grep -Fq 'Exec=maho-theme open' "$ROOT/share/applications/maho-themes.desktop" || fail "desktop entry does not use maho-theme open"
grep -Fq 'title = "^(Maho Themes)$"' "$ROOT/config/hypr/maho/core/windowing.lua" || fail "Maho Themes floating rule missing"
echo "PASS"

echo "=== preserved discovery and interaction ==="
grep -Fq 'FolderListModel {' "$THEMES/WallpaperPicker.qml" || fail "wallpaper folder model missing"
grep -Fq 'nameFilters: ["*.jpg", "*.jpeg", "*.png", "*.webp", "*.gif", "*.mp4", "*.mkv", "*.mov", "*.webm"]' "$THEMES/WallpaperPicker.qml" || fail "supported wallpaper formats changed"
grep -Fq 'sequence: "Left"' "$THEMES/WallpaperPicker.qml" || fail "keyboard navigation missing"
grep -Fq 'onClicked:' "$THEMES/WallpaperPicker.qml" || fail "mouse selection missing"
grep -Fq 'triggerOnlineSearch' "$THEMES/WallpaperPicker.qml" || fail "existing search missing"
grep -Fq 'export QS_WALLPAPER_DIR="$current_path"' "$ROOT/bin/maho-theme" || fail "current wallpaper directory discovery missing"
echo "PASS"

echo "=== safe process boundaries ==="
if grep -R -E 'Quickshell\.execDetached\(\["(ba)?sh",[[:space:]]*"-c"' "$THEMES"; then
    fail "QML constructs a shell program"
fi
if grep -R -E '(^|[^A-Za-z])(eval|bash -c|sh -c)([^A-Za-z]|$)' "$THEMES" --include='*.qml' --include='*.sh'; then
    fail "unsafe shell evaluation found"
fi
grep -Fq 'Quickshell.execDetached(["cp", "--", src, destDir + "/"])' "$THEMES/WallpaperPicker.qml" || fail "wallpaper import is not argument-safe"
grep -Fq 'applyProcess.command = [' "$THEMES/WallpaperPicker.qml" || fail "theme apply is not an argument-array process"
marker="$TMP/injection-marker"
bad="$TMP/missing \$(touch $marker).png"
if MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-theme" apply "$bad" dark >/dev/null 2>&1; then
    fail "nonexistent wallpaper was accepted"
fi
[ ! -e "$marker" ] || fail "wallpaper path was executed as shell input"
echo "PASS"

echo "=== CLI compatibility and one palette authority ==="
help="$(MAHO_ROOT="$ROOT" bash "$ROOT/bin/maho-theme")"
for command in open doctor generate show hash apply apply-hypr restore-hypr; do
    grep -q "maho-theme $command" <<<"$help" || fail "CLI command missing: $command"
done
grep -Fq 'theme/palette_v2.py' "$ROOT/bin/maho-theme" || fail "Palette V2 canonicalizer is not authoritative"
grep -Fq '/.cache/maho/theme/active.json' "$THEMES/MahoTheme.qml" || fail "active.json is not canonical for the UI"
if grep -R -E 'OKLab|OKLCH|canonicalize|palette_v2\.py' "$THEMES" --include='*.qml'; then
    fail "a second QML palette engine was introduced"
fi
[ ! -e "$THEMES/scripts/matugen_reload.sh" ] || fail "legacy competing palette reloader survived"
echo "PASS"

echo "=== transaction and rollback semantics ==="
grep -Fq 'before_wallpaper="$(maho_themes_current_wallpaper)"' "$ROOT/lib/themes_transaction.sh" || fail "previous wallpaper is not captured"
grep -Fq 'previous-active.json' "$ROOT/lib/themes_transaction.sh" || fail "previous active palette is not captured"
grep -Fq 'maho_themes_rollback' "$ROOT/lib/themes_transaction.sh" || fail "rollback path missing"
grep -Fq 'maho_themes_verify_wallpaper' "$ROOT/lib/themes_transaction.sh" || fail "wallpaper verification missing"
grep -Fq 'cmp -s "$candidate" "$CACHE/active.json"' "$ROOT/lib/themes_transaction.sh" || fail "palette commit verification missing"
grep -Fq 'MAHO_THEME_TEST_FAIL_AFTER_WALLPAPER' "$ROOT/lib/themes_transaction.sh" || fail "bounded failure injection missing"
echo "PASS"

echo "=== single instance and independent launch ==="
mkdir -p "$TMP/bin" "$TMP/wallpapers" "$TMP/cache"
printf '%s\n' '#!/usr/bin/env bash' 'printf "%s\\n" "$*" >> "$MAHO_THEMES_QUICKSHELL_LOG"' 'sleep 1.2' >"$TMP/bin/quickshell"
chmod +x "$TMP/bin/quickshell"
export MAHO_THEMES_QUICKSHELL_LOG="$TMP/quickshell.log"
test_path="$TMP/bin:/usr/bin:/bin"
XDG_CACHE_HOME="$TMP/cache" QS_WALLPAPER_DIR="$TMP/wallpapers" PATH="$test_path" \
    bash "$THEMES/scripts/open_picker.sh" &
first=$!
for _ in $(seq 1 30); do
    [ -s "$MAHO_THEMES_QUICKSHELL_LOG" ] && break
    sleep 0.05
done
[ -s "$MAHO_THEMES_QUICKSHELL_LOG" ] || fail "Maho Themes did not launch"
if XDG_CACHE_HOME="$TMP/cache" QS_WALLPAPER_DIR="$TMP/wallpapers" PATH="$test_path" \
    bash "$THEMES/scripts/open_picker.sh" >/dev/null 2>&1
then
    fail "duplicate Maho Themes instance was accepted"
fi
wait "$first"
[ "$(wc -l < "$MAHO_THEMES_QUICKSHELL_LOG")" -eq 1 ] || fail "more than one Quickshell instance launched"
grep -Fq -- '--no-duplicate -p' "$MAHO_THEMES_QUICKSHELL_LOG" || fail "independent Quickshell launch flags missing"
echo "PASS"

echo "=== lane isolation and old-picker rollback policy ==="
base=safety/maho-themes-pre-integration
if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$base"; then
    git -C "$ROOT" diff --quiet "$base" -- config/quickshell/maho-shell || fail "Maho Edge/Shell source changed"
    git -C "$ROOT" diff --quiet "$base" -- config/quickshell/maho-notify || fail "Notify source changed"
    git -C "$ROOT" diff --quiet "$base" -- '*launcher*' || fail "Launcher source changed"
fi
grep -Fq 'title = "^(wallpaper-picker)$"' "$ROOT/config/hypr/maho/core/windowing.lua" || fail "old picker window rule was removed"
grep -Fq 'without moving or modifying the old picker' "$THEMES/scripts/cache_paths.sh" || fail "old-picker rollback policy missing"
if grep -n -E 'rm .*legacy_dir|mv .*legacy_dir' "$THEMES/scripts/cache_paths.sh"; then
    fail "old picker cache can be deleted or moved"
fi
echo "PASS"

echo "ALL MAHO THEMES CONTRACTS PASS"
