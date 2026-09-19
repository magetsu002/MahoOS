#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LAUNCHER="$ROOT/bin/maho-launcher"
BACKEND="$ROOT/lib/maho_launcher_backend.py"
APP_MODEL="$ROOT/lib/maho_app_model.py"
QML="$ROOT/config/quickshell/maho-launcher"
WINDOW="$QML/MahoLauncherWindow.qml"
THEME="$QML/LauncherTheme.qml"
ROW="$QML/LauncherResultRow.qml"
APPICON="$QML/LauncherAppIcon.qml"
MODEL="$QML/LauncherBackend.qml"
BUTTON="$QML/LauncherIconButton.qml"
BACKDROP="$QML/LauncherBackdrop.qml"
DECORATIONS="$ROOT/config/hypr/maho/appearance/decorations.lua"
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
require_text "$WINDOW" 'WlrLayershell.namespace: "maho-launcher"' "launcher interaction namespace changed"
require_text "$WINDOW" 'top: true' "launcher no longer owns a full-screen interaction plane"
require_text "$WINDOW" 'bottom: true' "launcher no longer owns a full-screen interaction plane"
require_text "$WINDOW" 'left: true' "launcher no longer owns a full-screen interaction plane"
require_text "$WINDOW" 'right: true' "launcher no longer owns a full-screen interaction plane"
require_text "$WINDOW" 'surfaceWidth: 760' "approved surface width changed"
require_text "$WINDOW" 'surfaceHeight: 790' "stable surface height changed"
require_text "$WINDOW" 'LauncherIconButton' "functional QML header controls are missing"
require_text "$WINDOW" 'selectedSegment' "animated segmented selection surface is missing"
require_text "$WINDOW" 'highlightMoveDuration: 225' "selection motion is no longer animated"
require_text "$WINDOW" 'modeChanging' "mode content transition is missing"
require_text "$WINDOW" 'Behavior on opacity' "surface motion behaviors are missing"
require_text "$BUTTON" 'HoverHandler' "header controls lost hover state"
require_text "$BUTTON" 'TapHandler' "header controls lost press action"
require_text "$BUTTON" 'acceptedButtons: Qt.LeftButton' "header controls no longer own an explicit primary-button tap"
require_text "$BUTTON" 'symbol === "grid"' "custom crisp app-grid glyph is missing"
require_text "$BUTTON" 'symbol === "controls"' "custom crisp controls glyph is missing"
require_text "$ROW" 'height: 58' "application row breathing room changed"
require_text "$ROW" 'radius: 14' "application row state lost rounded geometry"
require_text "$ROW" 'height: 1' "premium application separator is missing"
require_text "$ROW" 'opacity: root.selected ? 0.05' "application separator became visually loud again"
require_text "$ROW" 'required property string name' "application name is not bound as a real model role"
require_text "$ROW" 'required property string entryId' "application desktop identity is not bound as a real model role"
require_text "$ROW" 'required property string iconPath' "resolved app artwork path is not bound as a real model role"
require_text "$ROW" 'readonly property var palette: root.theme || fallbackPalette' "row palette fallback no longer protects against binding ambiguity"
reject_text "$ROW" 'modelData' "delegate-local activation payload returned"
require_text "$ROW" 'root.activated(root.index)' "single-click does not publish the selected index"
require_text "$WINDOW" 'function activateItem(index)' "canonical activation entry point is missing"
require_text "$WINDOW" 'const authoritativeRow = backend.itemAt(index)' "activation does not use the current authoritative model row"
require_text "$WINDOW" 'backend.activate(authoritativeRow)' "authoritative row does not reach the backend"
require_text "$WINDOW" 'activateItem(resultList.currentIndex)' "Enter does not use canonical activation"
require_text "$WINDOW" 'root.activateItem(rowIndex)' "pointer activation does not use canonical activation"
require_text "$WINDOW" 'root.resetResultsToTop()' "fresh models do not reset selection to the top result"
require_text "$WINDOW" 'pointerMovementThreshold: 4' "passive pointer gating has no small movement threshold"
require_text "$WINDOW" 'PointerSelectionPolicy.hoverIndex(' "hover selection does not respect input authority"
require_text "$WINDOW" 'resetPointerAuthority()' "keyboard navigation cannot reclaim selection authority"
require_text "$ROW" 'onPointChanged:' "actual pointer motion cannot claim selection authority"
require_text "$ROW" 'LauncherAppIcon' "rows no longer use the real-artwork resolver"
reject_text "$ROW" 'monogram' "synthetic monogram placeholder returned"
reject_text "$ROW" 'visible: !root.iconReady' "synthetic failed-icon placeholder returned"
require_text "$APPICON" 'Quickshell.iconPath(value, "")' "app artwork no longer resolves through the active icon theme"
require_text "$APPICON" 'themed(idStem)' "desktop-id artwork fallback is missing"
require_text "$APPICON" 'themed(idTail)' "reverse-DNS desktop-id artwork fallback is missing"
require_text "$APPICON" 'appendUnique(output, root.iconPath)' "exact desktop artwork fallback is missing"
require_text "$APPICON" 'status === Image.Error' "failed real artwork does not advance to the next real candidate"
reject_text "$APPICON" 'application-x-executable' "generic executable placeholder returned"
reject_text "$WINDOW" 'mascot' "old launcher mascot returned"
reject_text "$WINDOW" 'to launch' "tutorial footer returned"
QMLTESTRUNNER="$(command -v qmltestrunner || true)"
if [ -z "$QMLTESTRUNNER" ] && [ -x /usr/lib/qt6/bin/qmltestrunner ]; then
    QMLTESTRUNNER=/usr/lib/qt6/bin/qmltestrunner
fi
[ -n "$QMLTESTRUNNER" ] || fail "Qt QML test runner is unavailable"
QT_QPA_PLATFORM=offscreen "$QMLTESTRUNNER" -input "$ROOT/tests/tst-maho-launcher-pointer-policy.qml"
echo "PASS"

echo "=== launcher navigation and browsing UX ==="
require_text "$WINDOW" 'function goAppsHome()' "app-grid header control lost its home/reset behavior"
require_text "$WINDOW" 'function runQuickCommand(action)' "quick actions no longer execute through the bounded backend"
require_text "$WINDOW" '["terminal", "files", "lock", "diagnostics"]' "quick actions escaped the approved command allowlist"
require_text "$WINDOW" 'property bool quickActionsOpen: false' "quick-actions surface state is missing"
require_text "$WINDOW" 'id: quickActions' "quick-actions glass surface is missing"
require_text "$WINDOW" 'text: "Quick actions"' "quick-actions surface lost its discoverable title"
require_text "$WINDOW" 'id: resultPageScroll' "result paging no longer animates"
require_text "$WINDOW" 'duration: 310' "result paging motion changed unexpectedly"
require_text "$WINDOW" 'function pageResults()' "show-more control no longer pages through results"
require_text "$WINDOW" 'return "Back to top"' "footer no longer exposes a clear return path"
require_text "$WINDOW" '"Show more apps"' "app paging affordance disappeared"
require_text "$WINDOW" 'rotation: root.resultsAtBottom ? 180 : 0' "footer chevron no longer reflects paging direction"
require_text "$WINDOW" 'font.pixelSize: 14' "primary application labels lost improved legibility"
require_text "$ROW" 'font.pixelSize: 14' "row name legibility regressed"
require_text "$ROW" 'font.pixelSize: 11' "row description legibility regressed"
echo "PASS"

echo "=== exact centered + draggable launcher geometry ==="
require_text "$WINDOW" 'Math.round((root.width - motionLayer.width) / 2)' "launcher horizontal centering is not exact"
require_text "$WINDOW" 'Math.round((root.height - motionLayer.height) / 2)' "launcher vertical centering is not exact"
require_text "$WINDOW" 'function centerSurface()' "launcher has no canonical centered placement"
require_text "$WINDOW" 'id: launcherDragArea' "launcher header has no drag authority"
require_text "$WINDOW" 'drag.target: motionLayer' "launcher drag does not move the material surface"
require_text "$WINDOW" 'preventStealing: true' "launcher drag can be stolen by child controls"
require_text "$WINDOW" 'drag.threshold: 2' "launcher drag does not engage promptly"
require_text "$WINDOW" 'drag.minimumX: root.surfaceMargin' "launcher drag is not bounded to the screen"
echo "PASS"

echo "=== Maho family glass material ==="
require_text "$THEME" '/maho/theme/active.json' "Palette V2 is not authoritative"
require_text "$THEME" 'function stableAccent' "family stable-accent behavior is missing"
require_text "$THEME" 'insetColor: mix(surfaceHigh, background, 0.36)' "launcher inset material drifted from Maho Link"
require_text "$THEME" 'familyShell: mix(surfaceHigh, background, 0.54)' "launcher shell mix drifted from Maho Link"
require_text "$THEME" 'shellFill: alpha(familyShell, 0.78)' "launcher shell opacity drifted from the denser frosted material"
require_text "$THEME" 'shellRim: alpha(foreground, 0.095)' "launcher shell rim no longer matches the glass material"
require_text "$THEME" 'selectedRow: alpha(mix(surfaceHigh, accent, 0.10), 0.54)' "selected row is not a raised Maho glass tier"
require_text "$THEME" 'resultsFill: alpha(mix(surfaceHigh, background, 0.64), 0.42)' "results well is not the low Maho glass tier"
[ -f "$BACKDROP" ] || fail "launcher catcher component is missing"
require_text "$BACKDROP" 'WlrLayershell.namespace: "maho-launcher-catcher"' "launcher catcher namespace is missing"
require_text "$BACKDROP" 'root.active ? 0.075 : 0' "launcher catcher dim alpha drifted"
require_text "$WINDOW" 'mask: Region { item: root.shown ? motionLayer : null }' "launcher foreground input is not card-bounded"
require_text "$DECORATIONS" 'name = "maho-launcher-material"' "launcher scoped blur rule is missing"
require_text "$DECORATIONS" 'match = { namespace = "maho-launcher" }' "launcher blur rule targets the wrong namespace"
require_text "$DECORATIONS" 'ignore_alpha = 0.16' "launcher blur alpha mask drifted"
reject_text "$DECORATIONS" 'namespace = "maho-launcher-catcher"' "launcher catcher must never be blurred"
require_text "$WINDOW" 'scale: root.shown ? 1 : (root.closing ? 1 : 0.992)' "launcher open-only scale motion is missing"
require_text "$WINDOW" 'y: root.shown ? 0 : (root.closing ? 0 : -4)' "launcher open-only lift motion is missing"
require_text "$WINDOW" 'duration: root.shown ? 145 : 68' "launcher fade timing drifted"
require_text "$WINDOW" 'interval: 85' "launcher close lifetime is too slow"
require_text "$QML/shell.qml" 'LauncherBackdrop {' "launcher shell does not own the unblurred catcher"
reject_text "$LAUNCHER" 'set_hyprland_material_rule' "launcher wrapper still mutates compositor blur rules"
reject_text "$LAUNCHER" 'maho-launcher-backdrop' "launcher wrapper still references old blur namespace"
echo "PASS"

echo "=== Launcher policy over shared app/XDG authority ==="
require_text "$MODEL" '["python3", root.backendPath, "apps"]' "QML no longer loads the native app index"
require_text "$MODEL" 'ListModel { id: visibleRows }' "visible rows are not published through a stable QML ListModel"
require_text "$MODEL" 'readonly property var activeModel: visibleRows' "ListView is not backed by the stable published model"
require_text "$MODEL" 'function itemAt(index)' "row activation lookup is missing"
require_text "$MODEL" 'visibleRows.append(row)' "real app snapshots are not copied into stable model roles"
require_text "$MODEL" 'property var appSource: []' "real app source state is missing"
require_text "$MODEL" 'function fuzzyScore' "Launcher fuzzy ranking is missing"
require_text "$MODEL" 'usageBoost' "Launcher usage/recency ranking is missing"
require_text "$MODEL" 'launcher-history.json' "Launcher bounded launch history is missing"
reject_text "$MODEL" 'DesktopEntries.applications.values' "launcher still depends on fragile live DesktopEntry QObject roles"
reject_text "$MODEL" 'ScriptModel' "plain application snapshots are still being wrapped in ScriptModel"

require_text "$BACKEND" 'from maho_app_model import (' "Launcher backend does not delegate to the shared Maho app model"
require_text "$BACKEND" 'discover_apps as shared_discover_apps' "shared desktop discovery is not authoritative"
require_text "$BACKEND" 'find_desktop_file' "shared desktop identity lookup is not exposed to Launcher"
require_text "$BACKEND" 'launch_app' "trusted app launching is not delegated to shared authority"
require_text "$BACKEND" 'resolve_icon_paths as shared_resolve_icon_paths' "shared icon resolution is not authoritative"
require_text "$BACKEND" 'return shared_discover_apps()' "Launcher discovery wrapper does not delegate"
require_text "$BACKEND" 'shared_resolve_icon_paths(entries)' "Launcher icon wrapper does not delegate"
reject_text "$BACKEND" 'def parse_desktop_entry(' "Launcher duplicated desktop-entry parsing authority"
reject_text "$BACKEND" 'def _assign_unique_aliases(' "Launcher duplicated canonical identity authority"

require_text "$APP_MODEL" 'QS_ICON_THEME' "shared app model does not honor the selected launcher icon theme"
require_text "$APP_MODEL" '"iconPath": ""' "shared desktop snapshots do not expose a resolved artwork path"
require_text "$APP_MODEL" 'configparser.ConfigParser(interpolation=None, strict=False)' "shared desktop parser is not safe for Exec percent tokens"
require_text "$APP_MODEL" 'OnlyShowIn' "shared desktop visibility semantics are incomplete"
require_text "$APP_MODEL" 'NoDisplay' "shared hidden desktop entries are not filtered"
require_text "$APP_MODEL" '"startupWmClass"' "shared canonical identity lacks StartupWMClass"
require_text "$APP_MODEL" '"aliases"' "shared canonical aliases are missing"
require_text "$APP_MODEL" '["gio", "launch", str(desktop_file)]' "shared trusted XDG launching is missing"
require_text "$APP_MODEL" 'gtk-launch' "shared desktop launch fallback is missing"

require_text "$BACKEND" 'def fuzzy_score(' "Launcher-specific file fuzzy policy disappeared"
require_text "$BACKEND" 'def file_search(' "Launcher Files mode search left Launcher ownership"
require_text "$BACKEND" 'def open_path(' "Launcher Files mode open path left Launcher ownership"
require_text "$BACKEND" 'def run_command(' "Launcher Commands mode left Launcher ownership"
require_text "$BACKEND" 'xdg-open' "Files mode open contract is missing"
require_text "$BACKEND" 'choices=("terminal", "files", "lock", "diagnostics")' "Commands allowlist is no longer exact"
reject_text "$BACKEND" 'shell=True' "backend introduced shell execution"
reject_text "$BACKEND" 'os.system' "backend introduced os.system"
reject_text "$APP_MODEL" 'shell=True' "shared app model introduced shell execution"
reject_text "$APP_MODEL" 'os.system' "shared app model introduced os.system"
reject_text "$LAUNCHER" 'rofi' "native launcher wrapper still depends on Rofi"
echo "PASS"

echo "=== stable overlay and compositor integration ==="
require_text "$WINDOW" 'property int pendingMode' "mode switch state is missing"
require_text "$WINDOW" 'backend.mode = root.pendingMode' "mode switch does not preserve a single shell"
require_text "$WINDOW" 'surfaceHeight: 790' "Commands can resize the outer surface"
require_text "$QML/shell.qml" 'LauncherBackdrop {' "launcher catcher is missing from shell composition"
reject_text "$LAUNCHER" 'maho-launcher-backdrop' "old launcher blur namespace returned"
reject_text "$LAUNCHER" 'set_hyprland_material_rule' "runtime blur-rule mutation returned"
require_text "$LAUNCHER" 'scoped launcher-card blur; catcher remains unblurred' "launcher doctor does not certify scoped blur design"
reject_text "$LAUNCHER" 'hl.config({' "launcher performs a global Hyprland mutation"
require_text "$QML/shell.qml" 'IpcHandler' "graceful launcher IPC is missing"
require_text "$QML/shell.qml" 'function close(): bool' "graceful close IPC is missing"
require_text "$LAUNCHER" 'quickshell ipc --pid "$pid" call launcher close' "wrapper does not request animated close"
require_text "$LAUNCHER" 'flock -n 9' "single-instance lock is missing"
require_text "$LAUNCHER" 'retire_stale_launchers' "Launcher can focus a stale runtime process"
require_text "$QML/shell.qml" 'MAHO_RUNTIME_IDENTITY' "Launcher does not expose immutable runtime identity"
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
StartupWMClass=MahoFixture
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
HOME="$TMP/home" XDG_DATA_HOME="$TMP/data" XDG_DATA_DIRS="$TMP/empty" QS_ICON_THEME=MahoTest \
python3 "$APP_MODEL" apps > "$TMP/shared-apps.json"
cmp -s "$TMP/apps.json" "$TMP/shared-apps.json" || fail "Launcher app output diverges from shared app/XDG authority"

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
if row["startupWmClass"] != "MahoFixture":
    raise SystemExit(f"canonical StartupWMClass missing: {row!r}")
if "mahofixture" not in row["aliases"]:
    raise SystemExit(f"canonical identity alias missing: {row!r}")
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
python3 -m py_compile "$APP_MODEL" "$BACKEND"
if command -v qmllint >/dev/null 2>&1; then
    qmllint "$QML"/*.qml >/dev/null 2>&1 || echo "INFO  qmllint needs the installed Quickshell import environment; native doctor is authoritative"
else
    echo "INFO  qmllint unavailable"
fi
echo "PASS"

echo "ALL NATIVE QML LAUNCHER CONTRACTS PASS"
