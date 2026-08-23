#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
QML="$ROOT/config/quickshell/maho-launcher/MahoLauncherWindow.qml"
THEME="$ROOT/config/quickshell/maho-launcher/LauncherTheme.qml"
SHELL="$ROOT/config/quickshell/maho-launcher/shell.qml"
RUNTIME="$ROOT/bin/maho-launcher"
BINDS="$ROOT/config/hypr/maho/core/binds.lua"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_file() { [ -r "$1" ] || fail "missing file: $1"; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
forbid_text() { ! grep -Fq -- "$2" "$1" || fail "$3"; }

echo "=== launcher files ==="
require_file "$QML"
require_file "$THEME"
require_file "$SHELL"
require_file "$RUNTIME"
require_file "$ROOT/config/quickshell/maho-launcher/assets/maho-logo.png"
require_file "$ROOT/config/quickshell/maho-launcher/assets/maho-mascot.png"
echo "PASS"

echo "=== adaptive material ==="
require_text "$THEME" '/maho/theme/active.json' "adaptive palette source is not consumed"
require_text "$THEME" 'property color background: palette(' "safe fallback theme is missing"
require_text "$THEME" 'property color panelTint:' "dynamic panel tint is missing"
require_text "$THEME" 'property color selectedResult:' "dynamic selected-row accent is missing"
require_text "$THEME" 'property color mascotGlow:' "dynamic mascot glow is missing"
forbid_text "$QML" '#d0bcff' "launcher view hardcodes the fallback purple"
echo "PASS"

echo "=== reference composition ==="
require_text "$QML" 'objectName: "MaterialPanel"' "material panel is missing"
require_text "$QML" 'text: "Maho"' "Maho header is missing"
require_text "$QML" 'text: "Launcher"' "Launcher header is missing"
require_text "$QML" 'Search apps, files, commands...' "search field is missing"
require_text "$QML" '"label": "Apps"' "Apps tab is missing"
require_text "$QML" '"label": "Files"' "Files tab is missing"
require_text "$QML" '"label": "Commands"' "Commands tab is missing"
require_text "$QML" 'property int currentMode: 0' "Apps is not the default mode"
require_text "$QML" 'objectName: "SelectedResultState"' "selected result state is missing"
require_text "$QML" 'objectName: "MascotLayer"' "mascot layer is missing"
require_text "$QML" 'enabled: false' "mascot layer may intercept pointer input"
require_text "$QML" 'id: materialPanel' "material panel identity is missing"
require_text "$QML" 'id: mascotLayer' "mascot is not a separate layer"
echo "PASS"

echo "=== interaction and discovery ==="
require_text "$QML" 'DesktopEntries.applications.values' "real desktop application discovery is missing"
require_text "$QML" 'entry.execute()' "safe desktop launch path is missing"
forbid_text "$QML" 'execString' "raw desktop Exec contents are consumed"
forbid_text "$QML" 'execDetached' "launcher bypasses DesktopEntry.execute()"
require_text "$QML" 'forceActiveFocus()' "focus-on-open is missing"
require_text "$QML" 'Qt.Key_Up' "Up navigation is missing"
require_text "$QML" 'Qt.Key_Down' "Down navigation is missing"
require_text "$QML" 'Qt.Key_Return' "Enter launch is missing"
require_text "$QML" 'Qt.Key_Escape' "Escape close is missing"
require_text "$QML" 'onEntered: resultList.currentIndex = index' "mouse hover selection is missing"
require_text "$QML" 'onClicked:' "mouse click launch is missing"
require_text "$QML" 'clip: true' "result list is not bounded"
require_text "$QML" 'boundsBehavior: Flickable.StopAtBounds' "result list is not scroll bounded"
echo "PASS"

echo "=== runtime isolation ==="
require_text "$QML" 'exclusiveZone: 0' "launcher reserves compositor space"
require_text "$QML" 'exclusionMode: ExclusionMode.Ignore' "launcher exclusion mode is not disabled"
require_text "$RUNTIME" 'flock -n 9' "duplicate-instance lock is missing"
require_text "$RUNTIME" 'refusing duplicate' "duplicate-instance protection is missing"
require_text "$RUNTIME" 'Search text and desktop-entry' "search-query logging policy is undocumented"
forbid_text "$RUNTIME" 'searchInput.text' "runtime logs search queries"
forbid_text "$QML" 'maho-shell' "Maho Edge is imported or referenced"
forbid_text "$QML" 'maho-notify' "Maho Notify is imported or referenced"
forbid_text "$SHELL" 'maho-shell' "launcher shell imports Maho Edge"
forbid_text "$SHELL" 'maho-notify' "launcher shell imports Maho Notify"
require_text "$BINDS" 'mainMod .. " + RETURN"' "existing application binding changed unexpectedly"
if rg -n 'maho-launcher' "$BINDS" >/dev/null; then
    fail "L1 changed the global launcher binding"
fi
LIVE_BINDS="${XDG_CONFIG_HOME:-$HOME/.config}/hypr/maho/core/binds.lua"
if [ -r "$LIVE_BINDS" ]; then
    require_text "$LIVE_BINDS" 'SUPER + CTRL + RETURN' "live rollback launcher binding is missing"
    require_text "$LIVE_BINDS" 'maho-rice-launcher' "live rollback launcher command is missing"
fi
bash -n "$RUNTIME"
echo "PASS"

echo "ALL MAHO LAUNCHER CONTRACTS PASS"
