#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/bin/maho-launcher"
BACKEND="$ROOT/lib/maho_launcher_backend.py"
QML="$ROOT/config/quickshell/maho-launcher"
WINDOW="$QML/MahoLauncherWindow.qml"
THEME="$QML/LauncherTheme.qml"
ROW="$QML/LauncherResultRow.qml"
MODEL="$QML/LauncherBackend.qml"
BUTTON="$QML/LauncherIconButton.qml"
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
require_text "$WINDOW" 'WlrLayershell.namespace: "maho-launcher"' "launcher namespace changed"
require_text "$WINDOW" 'top: true' "launcher no longer owns a full-screen glass plane"
require_text "$WINDOW" 'bottom: true' "launcher no longer owns a full-screen glass plane"
require_text "$WINDOW" 'left: true' "launcher no longer owns a full-screen glass plane"
require_text "$WINDOW" 'right: true' "launcher no longer owns a full-screen glass plane"
require_text "$WINDOW" 'surfaceWidth: 760' "approved surface width changed"
require_text "$WINDOW" 'surfaceHeight: 790' "stable surface height changed"
require_text "$WINDOW" 'LauncherIconButton' "functional QML header controls are missing"
require_text "$WINDOW" 'selectedSegment' "animated segmented selection surface is missing"
require_text "$WINDOW" 'highlightMoveDuration: 225' "selection motion is no longer animated"
require_text "$WINDOW" 'modeChanging' "mode content transition is missing"
require_text "$WINDOW" 'Behavior on opacity' "surface motion behaviors are missing"
require_text "$BUTTON" 'HoverHandler' "header controls lost hover state"
require_text "$BUTTON" 'TapHandler' "header controls lost press action"
require_text "$BUTTON" 'symbol === "grid"' "custom crisp app-grid glyph is missing"
require_text "$BUTTON" 'symbol === "controls"' "custom crisp controls glyph is missing"
require_text "$ROW" 'height: 58' "application row breathing room changed"
require_text "$ROW" 'radius: 14' "application row state lost rounded geometry"
require_text "$ROW" 'height: 1' "premium application separator is missing"
require_text "$ROW" 'opacity: root.selected ? 0.05' "application separator became visually loud again"
require_text "$ROW" 'required property string name' "application name is not bound as a real model role"
require_text "$ROW" 'required property string iconPath' "resolved app artwork path is not bound as a real model role"
require_text "$ROW" 'root.backend.itemAt(root.index)' "activation payload is not sourced from the published model"
reject_text "$WINDOW" 'mascot' "old launcher mascot returned"
reject_text "$WINDOW" 'to launch' "tutorial footer returned"
echo "PASS"

echo "=== Maho family glass material ==="
require_text "$THEME" '/maho/theme/active.json' "Palette V2 is not authoritative"
require_text "$THEME" 'function stableAccent' "family stable-accent behavior is missing"
require_text "$THEME" 'insetColor: mix(surfaceHigh, background, 0.36)' "launcher inset material drifted from Maho Link"
require_text "$THEME" 'familyShell: mix(surfaceHigh, background, 0.28)' "launcher shell material drifted from Maho Link"
require_text "$THEME" 'shellFill: alpha(familyShell, 0.965)' "launcher shell no longer uses the Maho family dark-glass density"
require_text "$THEME" 'shellRim: alpha(outline, 0.065)' "launcher shell rim no longer matches Maho Link subtlety"
require_text "$THEME" 'selectedRow: alpha(mix(insetColor, accent, 0.11), 0.97)' "selected row is not the Maho Link lifted material"
require_text "$THEME" 'resultsFill: alpha(mix(insetColor, background, 0.10), 0.92)' "results well drifted from Maho family material"
require_text "$THEME" 'shellTopSpecular: "transparent"' "full-size gradient can paint square pixels into rounded corners"
require_text "$THEME" 'shellAccentWash: "transparent"' "full-size gradient can paint square pixels into rounded corners"
require_text "$THEME" 'shellBottomShade: "transparent"' "full-size gradient can paint square pixels into rounded corners"
require_text "$WINDOW" 'backdropDim' "full-screen backdrop layer is missing"
require_text "$LAUNCHER" 'ignore_alpha = 0.02' "blur no longer participates through the low-alpha overlay"
require_text "$LAUNCHER" 'xray = false' "blur is bypassing live windows instead of blurring the actual desktop stack"
echo "PASS"

echo "=== own real application engine ==="
require_text "$MODEL" '["python3", root.backendPath, "apps"]' "QML no longer loads the native app index"
require_text "$MODEL" 'ListModel { id: visibleRows }' "visible rows are not published through a stable QML ListModel"
require_text "$MODEL" 'readonly property var activeModel: visibleRows' "ListView is not backed by the stable published model"
require_text "$MODEL" 'function itemAt(index)' "row activation lookup is missing"
require_text "$MODEL" 'visibleRows.append(row)' "real app snapshots are not copied into stable model roles"
require_text "$MODEL" 'property var appSource: []' "real app source state is missing"
require_text "$MODEL" 'function fuzzyScore' "Maho fuzzy ranking is missing"
require_text "$MODEL" 'usageBoost' "usage/recency ranking is missing"
require_text "$MODEL" 'launcher-history.json' "bounded launch history is missing"
reject_text "$MODEL" 'DesktopEntries.applications.values' "launcher still depends on fragile live DesktopEntry QObject roles"
reject_text "$MODEL" 'ScriptModel' "plain application snapshots are still being wrapped in ScriptModel"
require_text "$BACKEND" 'def discover_apps()' "Maho desktop-entry discovery is missing"
require_text "$BACKEND" 'def resolve_icon_paths(' "real app artwork resolver is missing"
require_text "$BACKEND" 'QS_ICON_THEME' "backend does not honor the selected launcher icon theme"
require_text "$BACKEND" '"iconPath": ""' "desktop snapshots do not expose a resolved artwork path"
require_text "$BACKEND" 'configparser.ConfigParser(interpolation=None, strict=False)' "desktop parser is not safe for Exec percent tokens"
require_text "$BACKEND" 'OnlyShowIn' "desktop visibility semantics are incomplete"
require_text "$BACKEND" 'NoDisplay' "hidden desktop entries are not filtered"
require_text "$BACKEND" 'gio", "launch"' "standards-aware desktop entry launching is missing"
require_text "$BACKEND" 'gtk-launch' "desktop launch fallback is missing"
require_text "$BACKEND" 'xdg-open' "Files mode open contract is missing"
require_text "$BACKEND" 'choices=("terminal", "files", "lock", "diagnostics")' "Commands allowlist is no longer exact"
reject_text "$BACKEND" 'shell=True' "backend introduced shell execution"
reject_text "$BACKEND" 'os.system' "backend introduced os.system"
reject_text "$LAUNCHER" 'rofi' "native launcher wrapper still depends on Rofi"
echo "PASS"

echo "=== stable overlay and compositor integration ==="
require_text "$WINDOW" 'property int pendingMode' "mode switch state is missing"
require_text "$WINDOW" 'backend.mode = root.pendingMode' "mode switch does not preserve a single shell"
require_text "$WINDOW" 'surfaceHeight: 790' "Commands can resize the outer surface"
require_text "$LAUNCHER" 'match = { namespace = "maho-launcher" }' "scoped blur namespace is missing"
require_text "$LAUNCHER" 'blur = true' "launcher blur participation is missing"
reject_text "$LAUNCHER" 'hl.config({' "launcher performs a global Hyprland mutation"
require_text "$QML/shell.qml" 'IpcHandler' "graceful launcher IPC is missing"
require_text "$QML/shell.qml" 'function close(): bool' "graceful close IPC is missing"
require_text "$LAUNCHER" 'quickshell ipc --pid "$pid" call launcher close' "wrapper does not request animated close"
require_text "$LAUNCHER" 'flock -n 9' "single-instance lock is missing"
echo "PASS"

echo "=== backend behavior ==="
mkdir -p "$TMP/home/Documents" "$TMP/data/applications" "$TMP/data/icons/MahoTest/scalable/apps" "$TMP/empty"
printf 'hello\n' > "$TMP/home/Documents/Project-Report.txt"
printf 'notes\n' > "$TMP/home/Documents/notes.txt"
printf '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"></svg>\n' > "$TMP/data/icons/MahoTest/scalable/apps/maho-test.svg"
cat > "$TMP/data/applications/maho-test.desktop" <<'EOF_DESKTOP'
[Desktop Entry]
Type=Application
Name=Maho Test
GenericName=Test Application
Comment=Real desktop entry fixture
Icon=maho-test
Exec=true
Categories=Utility;
EOF_DESKTOP
cat > "$TMP/data/applications/hidden.desktop" <<'EOF_DESKTOP'
[Desktop Entry]
Type=Application
Name=Hidden Fixture
NoDisplay=true
Exec=true
EOF_DESKTOP

HOME="$TMP/home" XDG_DATA_HOME="$TMP/data" XDG_DATA_DIRS="$TMP/empty" QS_ICON_THEME=MahoTest \
python3 "$BACKEND" apps > "$TMP/apps.json"
python3 - "$TMP/apps.json" "$TMP/data/icons/MahoTest/scalable/apps/maho-test.svg" <<'PY'
import json
import pathlib
import sys

rows = json.loads(pathlib.Path(sys.argv[1]).read_text())
expected_icon = pathlib.Path(sys.argv[2])
if [row["name"] for row in rows] != ["Maho Test"]:
    raise SystemExit(f"desktop discovery mismatch: {rows!r}")
row = rows[0]
if row["id"] != "maho-test.desktop" or row["icon"] != "maho-test":
    raise SystemExit(f"desktop roles mismatch: {row!r}")
if row["genericName"] != "Test Application":
    raise SystemExit(f"generic name missing: {row!r}")
if pathlib.Path(row["iconPath"]) != expected_icon:
    raise SystemExit(f"icon path was not resolved: {row!r}")
PY

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
