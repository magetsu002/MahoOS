#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$ROOT/apps/maho-settings"
QML="$APP/qml"
BACKEND="$ROOT/lib/maho_settings_backend.py"
WRAPPER="$ROOT/bin/maho-settings"
PKGBUILD="$ROOT/packaging/arch/PKGBUILD.in"
BINDINGS="$ROOT/config/hypr/maho/core/binds.lua"

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
for file in     "$APP/CMakeLists.txt"     "$APP/src/main.cpp"     "$APP/src/MahoSettingsBridge.cpp"     "$APP/src/MahoSettingsBridge.h"     "$QML/Main.qml"     "$QML/components/SettingsSidebar.qml"     "$QML/components/MahoSettingsTheme.qml"     "$QML/components/MahoSidebarItem.qml"     "$QML/components/MahoSegmentedControl.qml"     "$QML/components/MahoScrollBar.qml"     "$QML/components/StatePanel.qml"     "$QML/pages/AppearancePage.qml"     "$QML/pages/DisplaysPage.qml"     "$QML/pages/SoundPage.qml"     "$QML/pages/InputPage.qml"     "$QML/pages/PowerPage.qml"     "$QML/pages/NotificationsPage.qml"     "$QML/pages/RegionPage.qml"     "$QML/pages/ApplicationsPage.qml"     "$QML/pages/AboutPage.qml"     "$BACKEND"     "$WRAPPER"; do
    require_file "$file"
done
require_text "$APP/src/main.cpp" 'loadFromModule(QStringLiteral("Maho.Settings")' "Settings is not a native Qt/QML module"
require_text "$QML/Main.qml" 'readonly property real sidebarWidth: width < 980' "responsive sidebar breakpoint missing"
require_text "$QML/Main.qml" 'SettingsSidebar {' "category sidebar missing"
require_text "$QML/components/MahoSettingsTheme.qml" 'property bool reducedMotion: false' "Settings theme does not expose reduced motion"
require_text "$QML/components/MahoSwitch.qml" 'root.reducedMotion ? 0 : 120' "Settings switch ignores reduced motion"
require_file "$BINDINGS"
require_text "$QML/Main.qml" 'Loader {' "route/page loader missing"
require_text "$QML/components/SettingsSidebar.qml" 'Timer {' "deterministic search debounce missing"
require_text "$QML/components/SettingsSidebar.qml" 'root.searchRequested(query)' "deterministic search input missing"
require_text "$QML/Main.qml" 'route: "appearance"' "Appearance navigation route missing"
require_text "$QML/Main.qml" 'route: "displays"' "Displays navigation route missing"
require_text "$QML/Main.qml" 'route: "sound"' "Sound navigation route missing"
require_text "$QML/Main.qml" 'route: "input"' "input navigation route missing"
require_text "$QML/Main.qml" 'route: "power"' "Power navigation route missing"
require_text "$QML/Main.qml" 'route: "notifications"' "Notifications navigation route missing"
require_text "$QML/Main.qml" 'route: "region"' "Region & Time navigation route missing"
require_text "$QML/Main.qml" 'route: "applications"' "Applications navigation route missing"
require_text "$QML/Main.qml" 'route: "configuration"' "Configuration navigation route missing"
require_text "$QML/Main.qml" 'route: "diagnostics"' "Diagnostics navigation route missing"
require_text "$QML/Main.qml" 'route: "about"' "About navigation route missing"
require_text "$QML/Main.qml" 'case "shortcuts": return "pages/ShortcutsPage.qml"' "Shortcuts route is not implemented"
require_text "$QML/Main.qml" 'case "motion": return "pages/MotionPage.qml"' "Motion route is not implemented"
require_text "$QML/Main.qml" 'case "configuration": return "pages/ConfigurationPage.qml"' "Configuration route is not implemented"
require_text "$QML/Main.qml" 'case "diagnostics": return "pages/DiagnosticsPage.qml"' "Diagnostics route is not implemented"
echo PASS

echo "=== interaction and QML state hygiene ==="
for page in "$QML"/pages/*Page.qml; do
    reject_text "$page" 'readonly property var state:' "page overrides QQuickItem.state: $page"
done
require_text "$QML/components/MahoSwitch.qml" 'checkable: false' "switch can drift away from backend-owned state"
require_text "$QML/components/MahoSwitch.qml" 'signal toggleRequested(bool value)' "switch request signal missing"
require_text "$QML/components/MahoSwitch.qml" 'readonly property bool visualChecked:' "switch has no instant visual feedback"
require_text "$QML/components/MahoSwitch.qml" 'property bool busy: false' "switch cannot reconcile optimistic feedback with backend completion"
require_text "$QML/components/MahoSegmentedControl.qml" 'readonly property string visualValue:' "segmented control has no instant visual feedback"
require_text "$QML/components/MahoComboBox.qml" 'property bool backendOwned: false' "combo box backend-owned mode missing"
require_text "$QML/components/MahoComboBox.qml" 'delegateItem.highlighted' "combo highlight is not bound to its delegate"
reject_text "$QML/components/MahoComboBox.qml" 'parent.highlighted' "combo highlight relies on an invalid parent property"
require_text "$QML/components/MahoSlider.qml" 'property bool backendOwned: false' "slider backend-owned mode missing"
require_text "$QML/components/MahoTextField.qml" 'property bool backendOwned: false' "text field backend-owned mode missing"
require_text "$QML/Main.qml" 'id: dragRegion' "window dragging is not isolated from interactive content"
require_text "$APP/src/MahoSettingsBridge.cpp" 'const QString section = sectionForAction(action)' "successful mutations do not select a bounded refresh owner"
require_text "$APP/src/MahoSettingsBridge.cpp" 'confirmedState.canConvert<QVariantMap>()' "verified owner state is not reused after mutations"
require_text "$APP/src/MahoSettingsBridge.cpp" 'refreshSection(section)' "successful mutations still force an all-provider refresh"
require_text "$APP/src/MahoSettingsBridge.cpp" 'm_pendingRefreshSection = QStringLiteral("all")' "overlapping refreshes can drop a changed section"
require_text "$QML/pages/AppearancePage.qml" 'onActivated: root.bridge.openWallpaperPicker()' "Wallpaper row does not open the wallpaper owner"
require_text "$APP/src/MahoSettingsBridge.cpp" 'void MahoSettingsBridge::openWallpaperPicker()' "Wallpaper picker launch bridge is missing"
require_text "$BINDINGS" 'mainMod .. " + CTRL + SHIFT + S"' "SUPER+CTRL+SHIFT+S Settings shortcut is missing"
require_text "$BINDINGS" '"$HOME/.local/bin/maho-settings" run' "Settings shortcut does not launch the managed Settings wrapper"
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
require_text "$BACKEND" 'hypr_json(["monitors", "all", "-j"])' "Displays do not read real Hyprland output state"
require_text "$BACKEND" 'shutil.which("wpctl")' "Sound does not use WirePlumber wpctl"
require_text "$BACKEND" 'Path("/sys/class/power_supply")' "Power does not read kernel battery state"
require_text "$BACKEND" 'shutil.which("powerprofilesctl")' "Power profile hook does not delegate to power-profiles-daemon"
require_text "$BACKEND" 'root_command("maho-theme")' "Appearance does not reuse the Maho theme owner"
require_text "$BACKEND" 'root_command("maho-wallpaper")' "Appearance does not read the Maho wallpaper owner"
require_text "$BACKEND" 'primarySupported": False' "Settings invents a primary-display capability"
require_text "$BACKEND" 'root_command("maho-notify")' "Notifications do not delegate to Maho Notify"
require_text "$BACKEND" 'shutil.which("timedatectl")' "Region & Time does not delegate clock policy to timedatectl"
require_text "$BACKEND" 'shutil.which("localectl")' "Region & Time does not delegate locale policy to localectl"
require_text "$BACKEND" 'shutil.which("xdg-mime")' "Application defaults do not use XDG MIME authority"
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
require_text "$BACKEND" '"topology": sorted(row["name"] for row in baseline)' "display preview does not freeze output topology"
require_text "$BACKEND" '"proposed": proposed' "display preview does not retain the proposed persisted layout"
require_text "$BACKEND" '"The last active display cannot be disabled."' "last-display disable safety guard missing"
require_text "$BACKEND" '"_display-watch", token' "display preview lacks independent watchdog"
require_text "$BACKEND" 'start_new_session=True' "display watchdog is not process-independent"
require_text "$BACKEND" 'display_revert(token, automatic=True)' "watchdog does not auto-revert"
require_text "$BACKEND" 'hl.monitor({ ' "display mutations are not using the Hyprland Lua monitor authority"
require_text "$BACKEND" 'hl.dispatch(hl.dsp.focus' "focused-display semantics are not using the Hyprland Lua dispatcher"
require_text "$BACKEND" '_display_layout_matches' "display mutation readback verification is missing"
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
require_text "$QML/pages/NotificationsPage.qml" 'remain owned by Maho Notify' "Notifications does not state its owner"
require_text "$QML/pages/NotificationsPage.qml" 'does not currently expose notification sound, lock-screen visibility, or retention-duration preferences' "unsupported notification preferences are not explicit"
require_text "$QML/pages/RegionPage.qml" 'systemd-localed' "Region & Time does not state its locale owner"
require_text "$QML/pages/ApplicationsPage.qml" 'XDG MIME authority' "Applications does not state its defaults authority"
require_text "$QML/pages/ApplicationsPage.qml" 'does not invent a private default-terminal registry' "Applications invents an unsupported terminal default"
require_text "$QML/pages/DeferredPage.qml" 'must not invent unsupported system state' "deferred pages can imply fake capability"
echo PASS

echo "=== appearance and persistence hooks ==="
require_text "$APP/src/MahoPalette.cpp" 'maho/theme/active.json' "Settings does not consume canonical active palette"
require_text "$BACKEND" '"appearance.reduced_motion"' "reduced-motion intent hook missing"
require_text "$BACKEND" '"appearance.reduced_transparency"' "reduced-transparency intent hook missing"
require_text "$BACKEND" 'INPUT_CONFIG = SETTINGS_CONFIG / "input.json"' "input persistence missing"
require_text "$BACKEND" '"accelProfile": ("input:accel_profile"' "pointer acceleration persistence path missing"
require_text "$BACKEND" '"mouseNaturalScroll": ("input:natural_scroll"' "mouse natural-scroll persistence path missing"
require_text "$BACKEND" '"leftHanded": ("input:left_handed"' "primary-button persistence path missing"
require_text "$BACKEND" 'hl.config(' "Hyprland input/appearance mutations are not using Lua config authority"
require_text "$BACKEND" 'hl.device({ ' "per-device touchpad speed is not using Hyprland Lua device authority"
require_text "$QML/pages/InputPage.qml" 'touchpadSensitivity' "touchpad speed control is missing"
require_text "$BACKEND" 'input_set("keyboardLayout"' "keyboard-layout entry point is not using input persistence"
require_text "$BACKEND" 'DISPLAY_CONFIG = SETTINGS_CONFIG / "displays.json"' "display persistence missing"
reject_text "$BACKEND" 'hypr(["keyword"' "legacy Hyprland keyword mutation can false-report success under Lua config"
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
require_text "$QML/pages/PowerPage.qml" 'never triggers suspend, reboot, or shutdown' "Power UI does not state its bounded control contract"
require_text "$BACKEND" '"sessionPolicyControlAvailable": False' "unsupported screen/suspend/lid policy is not explicit"
require_text "$QML/pages/PowerPage.qml" 'No supported user-scoped session policy backend is available' "Power UI hides unavailable session-policy authority"
echo PASS



echo "=== bounded daily-driver owner paths ==="
require_text "$BACKEND" 'run([command, "start" if enabled else "stop"]' "notification enable/disable bypasses Maho Notify"
require_text "$BACKEND" 'run([command, "start" if enabled else "stop"]' "notification enable/disable bypasses Maho Notify"
require_text "$BACKEND" 'run([command, "dnd", "on" if enabled else "off"]' "DND mutation bypasses Maho Notify"
require_text "$BACKEND" 'run([command, "history", "clear"]' "notification history mutation bypasses Maho Notify"
require_text "$BACKEND" '[executable, "set-timezone", value]' "timezone mutation is missing"
require_text "$BACKEND" '[executable, "set-ntp", "true" if enabled else "false"]' "automatic-time mutation is missing"
require_text "$BACKEND" '[executable, "set-locale", f"LANG={value}"]' "locale mutation is missing"
require_text "$BACKEND" '[executable, "default", desktop_id, mime]' "XDG default-app mutation is missing"
require_text "$BACKEND" 'application_mime_default' "bounded MIME association mutation is missing"
require_text "$QML/pages/ApplicationsPage.qml" 'Default associations' "MIME/default association UI is missing"
require_text "$QML/pages/ApplicationsPage.qml" 'Effective XDG session entries' "autostart list is missing"
require_text "$BACKEND" 'WirePlumber did not confirm the requested volume.' "sound mutation readback verification is missing"
reject_text "$QML/pages/ApplicationsPage.qml" 'Android' "unsupported Android-style permission model leaked into Applications"
echo PASS

echo "=== production delivery and provenance ==="
require_text "$APP/CMakeLists.txt" 'MAHO_SETTINGS_SOURCE_FINGERPRINT' "native build lacks embedded source identity"
require_text "$WRAPPER" 'verified_binary' "wrapper does not verify binary provenance"
require_text "$WRAPPER" 'MAHO_SETTINGS_BUILD_DIR' "isolated development build path missing"
require_text "$PKGBUILD" 'build-maho-settings' "Arch package does not build Maho Settings"
require_text "$PKGBUILD" 'apps/maho-settings/prebuilt/maho-settings' "Arch package does not ship native Settings artifact"
require_text "$PKGBUILD" 'maho-settings-wrapper' "Arch package does not expose Settings runtime wrapper"
require_file "$ROOT/packaging/arch/maho-settings-wrapper"
require_text "$ROOT/bin/maho-setup" 'maho-files maho-link maho-settings maho-lock' "runtime setup does not publish the maho-settings user wrapper"
bash -n "$WRAPPER" "$ROOT/packaging/arch/maho-settings-wrapper"
python3 -m py_compile "$BACKEND" "$APP/source-fingerprint.py"
echo PASS

echo "=== focused backend tests ==="
python3 -m unittest -v "$ROOT/tests/test_maho_settings_backend.py"
echo PASS

echo "PASS  Maho Settings V1 foundation contracts"
