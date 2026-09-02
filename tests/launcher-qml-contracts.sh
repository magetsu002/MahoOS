#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/bin/maho-launcher"
BACKEND="$ROOT/lib/maho_launcher_backend.py"
QML="$ROOT/config/quickshell/maho-launcher"
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

echo "=== native QML authority ==="
require_text "$QML/shell.qml" 'ShellId maho-launcher' "launcher has no independent Quickshell identity"
require_text "$QML/MahoLauncherWindow.qml" 'WlrLayershell.namespace: "maho-launcher"' "launcher namespace changed"
require_text "$QML/MahoLauncherWindow.qml" 'implicitWidth: 760' "approved width changed"
require_text "$QML/MahoLauncherWindow.qml" 'implicitHeight: 730' "mode-stable shell height changed"
require_text "$QML/MahoLauncherWindow.qml" 'LauncherIconButton' "functional QML header controls are missing"
require_text "$QML/MahoLauncherWindow.qml" 'selectedSegment' "animated segmented selection surface is missing"
require_text "$QML/MahoLauncherWindow.qml" 'highlightMoveDuration: 185' "selection motion is no longer animated"
require_text "$QML/MahoLauncherWindow.qml" 'modeChanging' "mode content transition is missing"
require_text "$QML/MahoLauncherWindow.qml" 'Behavior on opacity' "surface motion behaviors are missing"
require_text "$QML/LauncherIconButton.qml" 'HoverHandler' "header controls lost hover state"
require_text "$QML/LauncherIconButton.qml" 'TapHandler' "header controls lost press action"
require_text "$QML/LauncherResultRow.qml" 'height: 58' "application row breathing room changed"
require_text "$QML/LauncherResultRow.qml" 'height: 1' "premium application separator is missing"
require_text "$QML/LauncherResultRow.qml" 'IconImage' "real icon-theme artwork is not used"
reject_text "$QML/MahoLauncherWindow.qml" 'mascot' "old launcher mascot returned"
reject_text "$QML/MahoLauncherWindow.qml" 'to launch' "tutorial footer returned"
reject_text "$QML/MahoLauncherWindow.qml" 'arrives in L2' "placeholder modes returned"
echo "PASS"

echo "=== own launcher engine ==="
require_text "$QML/LauncherBackend.qml" 'DesktopEntries.applications.values' "desktop application discovery is missing"
require_text "$QML/LauncherBackend.qml" 'function fuzzyScore' "Maho fuzzy ranking is missing"
require_text "$QML/LauncherBackend.qml" 'usageBoost' "usage/recency ranking is missing"
require_text "$QML/LauncherBackend.qml" 'launcher-history.json' "bounded launch history is missing"
require_text "$QML/LauncherBackend.qml" 'Process {' "Files mode does not use the bounded async helper"
require_text "$QML/LauncherBackend.qml" 'refilterCommands' "curated Commands mode is missing"
require_text "$BACKEND" 'gio", "launch"' "standards-aware desktop entry launching is missing"
require_text "$BACKEND" 'gtk-launch' "desktop launch fallback is missing"
require_text "$BACKEND" 'xdg-open' "Files mode open contract is missing"
require_text "$BACKEND" 'choices=("terminal", "files", "lock", "diagnostics")' "Commands allowlist is no longer exact"
reject_text "$BACKEND" 'shell=True' "backend introduced shell execution"
reject_text "$BACKEND" 'os.system' "backend introduced os.system"
reject_text "$LAUNCHER" 'rofi' "native launcher wrapper still depends on Rofi"
reject_text "$QML/MahoLauncherWindow.qml" 'rofi' "QML frontend still references Rofi"
echo "PASS"

echo "=== Maho material and icon policy ==="
require_text "$QML/LauncherTheme.qml" '/maho/theme/active.json' "Palette V2 is not authoritative"
require_text "$QML/LauncherTheme.qml" 'function stableAccent' "family stable-accent behavior is missing"
require_text "$QML/LauncherTheme.qml" 'property color shellFill' "frosted shell material is missing"
require_text "$QML/LauncherTheme.qml" 'property color divider' "row-divider material token is missing"
require_text "$QML/LauncherTheme.qml" 'property color selectedRow' "selected-row material is missing"
require_text "$LAUNCHER" 'Papirus-Dark Papirus Tela-circle-dark Tela-circle Tela' "high-coverage icon preference is missing"
require_text "$LAUNCHER" 'QS_ICON_THEME' "Quickshell icon-theme selection is not wired"
require_text "$QML/LauncherResultRow.qml" 'Quickshell.iconPath' "application icons do not resolve through the native theme"
reject_text "$QML/LauncherResultRow.qml" 'tint:' "full-color application artwork is being recolored"
echo "PASS"

echo "=== stable modes and safe compositor integration ==="
require_text "$QML/MahoLauncherWindow.qml" 'property int pendingMode' "mode switch state is missing"
require_text "$QML/MahoLauncherWindow.qml" 'backend.mode = root.pendingMode' "mode switch does not preserve a single shell"
require_text "$QML/MahoLauncherWindow.qml" 'implicitHeight: 730' "Commands can resize the outer shell"
require_text "$LAUNCHER" 'match = { namespace = "maho-launcher" }' "scoped blur namespace is missing"
require_text "$LAUNCHER" 'blur = true' "launcher blur participation is missing"
require_text "$LAUNCHER" 'xray = true' "wallpaper backdrop cannot participate through blur"
reject_text "$LAUNCHER" 'hl.config({' "launcher performs a global Hyprland mutation"
require_text "$QML/shell.qml" 'IpcHandler' "graceful launcher IPC is missing"
require_text "$QML/shell.qml" 'function close(): bool' "graceful close IPC is missing"
require_text "$LAUNCHER" 'quickshell ipc --pid "$pid" call launcher close' "wrapper does not request animated close"
require_text "$LAUNCHER" 'flock -n 9' "single-instance lock is missing"
echo "PASS"

echo "=== backend behavior ==="
mkdir -p "$TMP/home/Documents" "$TMP/data/applications"
printf 'hello\n' > "$TMP/home/Documents/Project-Report.txt"
printf 'notes\n' > "$TMP/home/Documents/notes.txt"
cat > "$TMP/data/applications/maho-test.desktop" <<'EOF_DESKTOP'
[Desktop Entry]
Type=Application
Name=Maho Test
Exec=true
EOF_DESKTOP

HOME="$TMP/home" XDG_DATA_HOME="$TMP/data" XDG_DATA_DIRS="$TMP/empty" \
python3 - "$BACKEND" "$TMP/data/applications/maho-test.desktop" <<'PY'
import importlib.util
import pathlib
import sys

backend_path = pathlib.Path(sys.argv[1])
expected = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("maho_launcher_backend", backend_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
resolved = module.find_desktop_file("maho-test.desktop")
if resolved != expected:
    raise SystemExit(f"desktop lookup mismatch: {resolved!r}")
PY

HOME="$TMP/home" python3 "$BACKEND" files --query report --limit 5 > "$TMP/files.json"
python3 - "$TMP/files.json" <<'PY'
import json
import pathlib
import sys

rows = json.loads(pathlib.Path(sys.argv[1]).read_text())
if not rows:
    raise SystemExit("file search returned no rows")
if not any(row["name"] == "Project-Report.txt" for row in rows):
    raise SystemExit(f"expected Project-Report.txt, got {rows!r}")
if len(rows) > 5:
    raise SystemExit("file-search limit was ignored")
PY

echo "PASS"

echo "=== syntax ==="
bash -n "$LAUNCHER"
python3 -m py_compile "$BACKEND"
if command -v qmllint >/dev/null 2>&1; then
    qmllint "$QML"/*.qml >/dev/null 2>&1 || echo "INFO  qmllint needs the installed Quickshell import environment; native doctor is authoritative"
else
    echo "INFO  qmllint unavailable"
fi
echo "PASS"

echo "ALL NATIVE QML LAUNCHER CONTRACTS PASS"
