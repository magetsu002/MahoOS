#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/maho-settings"
QML="$APP/qml"
BACKEND="$ROOT/lib/maho_settings_backend.py"
WRAPPER="$ROOT/bin/maho-settings"
PKGBUILD="$ROOT/packaging/arch/PKGBUILD.in"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_file() { [ -f "$1" ] || fail "missing $1"; }
require_text() {
    local file="$1" text="$2" message="$3"
    grep -Fq -- "$text" "$file" || fail "$message"
}
reject_text() {
    local file="$1" text="$2" message="$3"
    if grep -Fq -- "$text" "$file"; then
        fail "$message"
    fi
}

echo "=== native persistent application structure ==="
for file in     "$APP/CMakeLists.txt"     "$APP/src/main.cpp"     "$APP/src/MahoSettingsBridge.cpp"     "$APP/src/MahoSettingsBridge.h"     "$QML/Main.qml"     "$QML/components/SettingsSidebar.qml"     "$QML/components/StatePanel.qml"     "$QML/pages/AppearancePage.qml"     "$QML/pages/DisplaysPage.qml"     "$QML/pages/SoundPage.qml"     "$QML/pages/InputPage.qml"     "$QML/pages/PowerPage.qml"     "$QML/pages/AboutPage.qml"     "$BACKEND"     "$WRAPPER"; do
    require_file "$file"
done
require_text "$APP/src/main.cpp" 'loadFromModule(QStringLiteral("Maho.Settings")' "Settings is not a native Qt/QML module"
require_text "$QML/Main.qml" 'readonly property bool narrow: width < 820' "responsive layout breakpoint missing"
require_text "$QML/Main.qml" 'SettingsSidebar {' "category sidebar missing"
require_text "$QML/Main.qml" 'Loader {' "route/page loader missing"
require_text "$QML/Main.qml" 'searchDebounce' "deterministic search input missing"
require_text "$QML/Main.qml" 'route: "appearance"' "Appearance navigation route missing"
require_text "$QML/Main.qml" 'route: "displays"' "Displays navigation route missing"
require_text "$QML/Main.qml" 'route: "sound"' "Sound navigation route missing"
require_text "$QML/Main.qml" 'route: "input"' "input navigation route missing"
require_text "$QML/Main.qml" 'route: "power"' "Power navigation route missing"
require_text "$QML/Main.qml" 'route: "system"' "System navigation route missing"
echo PASS

echo "=== deterministic search contract ==="
python3 - "$BACKEND" <<'PY'
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("settings_backend", path)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)
expected = {
    "refresh": ("Displays / Refresh Rate", "displays", "displays"),
    "mic": ("Sound / Input", "sound", "sound"),
    "recovery": ("System / Recovery", "system", "recovery"),
}
for query, want in expected.items():
    result = mod.search(query)
    assert result, query
    got = (result[0]["label"], result[0]["route"], result[0]["target"])
    assert got == want, (query, got, want)
    assert result == mod.search(query), "search must be deterministic"
PY
echo PASS

echo "=== backend authority map ==="
require_text "$BACKEND" 'hypr_json(["monitors", "-j"])' "Displays do not read real Hyprland output state"
require_text "$BACKEND" 'shutil.which("wpctl")' "Sound does not use WirePlumber wpctl"
require_text "$BACKEND" 'Path("/sys/class/power_supply")' "Power does not read kernel battery state"
require_text "$BACKEND" 'shutil.which("powerprofilesctl")' "Power profile hook does not delegate to power-profiles-daemon"
require_text "$BACKEND" 'root_command("maho-theme")' "Appearance does not reuse the Maho theme owner"
require_text "$BACKEND" 'root_command("maho-wallpaper")' "Appearance does not read the Maho wallpaper owner"
require_text "$BACKEND" 'primarySupported": False' "Settings invents a primary-display capability"
reject_text "$BACKEND" 'nmcli' "Settings duplicated Maho Link NetworkManager quick-connect flows"
reject_text "$BACKEND" 'bluetoothctl' "Settings duplicated Bluetooth quick-connect flows"
reject_text "$BACKEND" 'maho-guardian' "Settings imported Guardian logic"
reject_text "$BACKEND" 'maho-update' "Settings imported update mutation logic"
reject_text "$BACKEND" 'maho-recovery' "Settings imported recovery mutation logic"
reject_text "$BACKEND" 'sudo ' "UI backend gained unbounded sudo authority"
reject_text "$BACKEND" 'pkexec' "UI backend gained an undeclared privileged boundary"
echo PASS

echo "=== safe display preview/revert architecture ==="
require_text "$BACKEND" 'DISPLAY_ROLLBACK_SECONDS = 15' "bounded display rollback window missing"
require_text "$BACKEND" 'TX_DIR = SETTINGS_STATE / "display-transactions"' "display transaction evidence missing"
require_text "$BACKEND" '"baseline": baseline' "display preview does not capture exact baseline"
require_text "$BACKEND" '"_display-watch", token' "display preview lacks independent watchdog"
require_text "$BACKEND" 'display_revert(token, automatic=True)' "watchdog does not auto-revert"
require_text "$BACKEND" '_apply_display_rows([row for row in current if isinstance(row, dict)])' "session apply lacks fallback to preexisting layout"
require_text "$QML/pages/DisplaysPage.qml" 'Keep this display configuration?' "display confirmation UI missing"
require_text "$QML/pages/DisplaysPage.qml" 'Reverting in ' "rollback countdown UI missing"
echo PASS

echo "=== truthful unavailable/error and deferred states ==="
require_text "$QML/components/StatePanel.qml" 'property string title: "Unavailable"' "shared unavailable component missing"
require_text "$QML/pages/SoundPage.qml" 'Audio backend unavailable' "Sound unavailable state missing"
require_text "$QML/pages/DisplaysPage.qml" 'Display backend unavailable' "Displays unavailable state missing"
require_text "$QML/pages/InputPage.qml" 'Input state unavailable' "Input unavailable state missing"
require_text "$QML/pages/AboutPage.qml" 'Deferred V1 pages' "deferred V1 scope is not explicit"
require_text "$QML/pages/DeferredPage.qml" 'must not invent unsupported system state' "deferred pages can imply fake capability"
echo PASS

echo "=== appearance and persistence hooks ==="
require_text "$APP/src/MahoPalette.cpp" 'maho/theme/active.json' "Settings does not consume canonical active palette"
require_text "$BACKEND" '"appearance.reduced_motion"' "reduced-motion intent hook missing"
require_text "$BACKEND" '"appearance.reduced_transparency"' "reduced-transparency intent hook missing"
require_text "$BACKEND" 'INPUT_CONFIG = SETTINGS_CONFIG / "input.json"' "input persistence missing"
require_text "$BACKEND" 'DISPLAY_CONFIG = SETTINGS_CONFIG / "displays.json"' "display persistence missing"
require_text "$APP/io.maho.Settings.Session.desktop" 'Exec=maho-settings apply-session' "confirmed session preferences are not reapplied"
echo PASS

echo "=== power/user-control boundary ==="
python3 - "$BACKEND" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
for forbidden in ("systemctl reboot", "systemctl poweroff", "systemctl suspend", "shutdown -", "reboot -"):
    assert forbidden not in text, forbidden
PY
require_text "$QML/pages/PowerPage.qml" 'never reboots, shuts down, or suspends' "Power UI does not state its bounded control contract"
echo PASS

echo "=== production delivery and provenance ==="
require_text "$APP/CMakeLists.txt" 'MAHO_SETTINGS_SOURCE_FINGERPRINT' "native build lacks embedded source identity"
require_text "$WRAPPER" 'verified_binary' "wrapper does not verify binary provenance"
require_text "$WRAPPER" 'MAHO_SETTINGS_BUILD_DIR' "isolated development build path missing"
require_text "$PKGBUILD" 'build-maho-settings' "Arch package does not build Maho Settings"
require_text "$PKGBUILD" 'apps/maho-settings/prebuilt/maho-settings' "Arch package does not ship native Settings artifact"
require_text "$PKGBUILD" 'maho-settings-wrapper' "Arch package does not expose Settings runtime wrapper"
require_file "$ROOT/packaging/arch/maho-settings-wrapper"
bash -n "$WRAPPER" "$ROOT/packaging/arch/maho-settings-wrapper"
python3 -m py_compile "$BACKEND" "$APP/source-fingerprint.py"
echo PASS

echo "=== focused backend tests ==="
python3 -m unittest -v "$ROOT/tests/test_maho_settings_backend.py"
echo PASS

echo "PASS  Maho Settings V1 foundation contracts"
