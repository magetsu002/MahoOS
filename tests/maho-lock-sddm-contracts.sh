#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$ROOT/bin/maho-lock-sddm-install"
THEME="$ROOT/config/sddm/maho-lock"

fail() { printf 'FAIL  %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS  %s\n' "$*"; }

bash -n "$INSTALLER" || fail "SDDM installer syntax"
for file in Main.qml MahoSddmIcon.qml MahoSddmActionButton.qml metadata.desktop theme.conf; do
    [ -r "$THEME/$file" ] || fail "missing SDDM theme source $file"
done
pass "SDDM source and installer syntax"

grep -Fq 'maho-lock-sddm-install' "$ROOT/bin/maho-setup" \
    || fail "SDDM installer omitted from the durable runtime"
grep -Fq -- '--with-sddm' "$ROOT/bin/maho-setup" \
    || fail "durable setup has no explicit SDDM activation path"
grep -Fq -- '--with-sddm' "$ROOT/packaging/arch/maho-install" \
    || fail "packaged installer cannot request SDDM activation"
grep -Fq "'imagemagick'" "$ROOT/packaging/arch/PKGBUILD.in" \
    || fail "packaged SDDM avatar preparation lacks ImageMagick"
grep -Fq "'qt6-5compat'" "$ROOT/packaging/arch/PKGBUILD.in" \
    || fail "packaged Qt 6 greeter lacks its compatibility module"
pass "SDDM integration is reachable from release setup"

grep -Fq 'import SddmComponents 2.0' "$THEME/Main.qml" \
    || fail "SDDM component API import missing"
grep -Fq 'import Qt5Compat.GraphicalEffects' "$THEME/Main.qml" \
    || fail "SDDM Qt 6 greeter compatibility import missing"
grep -Fxq 'QtVersion=6' "$THEME/metadata.desktop" \
    || fail "SDDM theme can fall back to the unavailable Qt 5 greeter"
grep -Fq 'sddm.login(loginUser, passwordInput.text, sessionIndex)' "$THEME/Main.qml" \
    || fail "SDDM authentication handoff missing"
grep -Fq 'function onLoginFailed()' "$THEME/Main.qml" \
    || fail "failed authentication recovery missing"
grep -Fq 'anchors.centerIn: parent' "$THEME/Main.qml" \
    || fail "centered action content missing"
grep -Fq 'fillMode: Image.PreserveAspectCrop' "$THEME/Main.qml" \
    || fail "native wallpaper crop missing"
grep -Fq 'Math.min(2.4' "$THEME/Main.qml" \
    || fail "SDDM HiDPI composition is still capped below the preview scale"
if grep -Fq 'Canvas {' "$THEME/MahoSddmIcon.qml"; then
    fail "SDDM still renders low-density hand-drawn canvas icons"
fi
grep -Fq 'source: "assets/icons/" + root.name + ".svg"' "$THEME/MahoSddmIcon.qml" \
    || fail "SDDM vector icon source missing"
grep -Fq 'sourceSize.width: Math.max(1024' "$THEME/Main.qml" \
    || fail "SDDM avatar decode density regressed"
grep -Fq 'runuser -u "$account"' "$INSTALLER" \
    || fail "root SDDM setup decodes user-selected avatars as root"
if grep -Eq 'OpacityMask|MultiEffect' "$THEME/Main.qml"; then
    fail "SDDM avatar still depends on renderer-specific shader masking"
fi
grep -Fq 'hoverEnabled: true' "$THEME/MahoSddmActionButton.qml" \
    || fail "SDDM action hover state missing"
grep -Fq 'Behavior on scale' "$THEME/MahoSddmActionButton.qml" \
    || fail "SDDM action motion feedback missing"
grep -Fq 'onTriggered: root.chooseNextSession()' "$THEME/Main.qml" \
    || fail "SDDM session selector is still static"
grep -Fq 'visible: root.keyboardLayoutCount > 1' "$THEME/Main.qml" \
    || fail "single keyboard layout is still presented as a no-op button"
grep -Fq 'visible: root.sessionNames.length > 1' "$THEME/Main.qml" \
    || fail "single session is still presented as a no-op button"
grep -Fq 'id: eyePointer' "$THEME/Main.qml" \
    || fail "password visibility control references a missing pointer authority"
grep -Fq 'PASS  SDDM live interaction guards' "$INSTALLER" \
    || fail "installed status does not verify the interaction repair"
pass "SDDM authentication and accepted visual contracts"

QMLTESTRUNNER="$(command -v qmltestrunner || true)"
if [ -z "$QMLTESTRUNNER" ] && [ -x /usr/lib/qt6/bin/qmltestrunner ]; then
    QMLTESTRUNNER=/usr/lib/qt6/bin/qmltestrunner
fi
[ -n "$QMLTESTRUNNER" ] || fail "Qt QML test runner is unavailable"
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software \
    "$QMLTESTRUNNER" -input "$ROOT/tests/tst-maho-sddm-action-button.qml"
pass "native SDDM action interaction"

sandbox="$(mktemp -d)"
trap 'rm -rf -- "$sandbox"' EXIT
export MAHO_SDDM_ALLOW_UNPRIVILEGED=1
export MAHO_SDDM_THEME_ROOT="$sandbox/themes"
export MAHO_SDDM_CONFIG_ROOT="$sandbox/config"
export MAHO_SDDM_STATE_ROOT="$sandbox/state"

bash "$INSTALLER" install >/dev/null
bash "$INSTALLER" status >/dev/null
grep -Fxq '# managed-by: maho-lock-sddm v1' "$sandbox/config/90-maho-lock.conf" \
    || fail "managed SDDM config marker missing"
grep -Fxq 'Current=maho-lock' "$sandbox/config/90-maho-lock.conf" \
    || fail "persistent SDDM theme selection missing"
[ -s "$sandbox/themes/maho-lock/assets/wallpaper" ] \
    || fail "staged wallpaper missing"
[ -s "$sandbox/themes/maho-lock/assets/avatar.png" ] \
    || fail "staged rounded avatar missing"
magick identify "$sandbox/themes/maho-lock/assets/avatar.png" | grep -Fq '1024x1024' \
    || fail "staged avatar is not the high-resolution square contract"
magick identify -verbose "$sandbox/themes/maho-lock/assets/avatar.png" | grep -Fq 'Alpha:' \
    || fail "staged avatar lost its circular alpha mask"
grep -Fxq 'managed-by-maho-lock-sddm-v1' \
    "$sandbox/themes/maho-lock/.managed-by-maho-lock-sddm" \
    || fail "managed theme marker missing"
grep -Fxq 'QtVersion=6' "$sandbox/themes/maho-lock/metadata.desktop" \
    || fail "staged theme lost its Qt 6 greeter selection"
for file in lock.svg eye.svg eye-off.svg power.svg keyboard.svg restart.svg session.svg; do
    [ -s "$sandbox/themes/maho-lock/assets/icons/$file" ] \
        || fail "staged vector icon missing: $file"
done
[ -s "$sandbox/themes/maho-lock/MahoSddmActionButton.qml" ] \
    || fail "staged interactive action component missing"
pass "sandbox persistent SDDM installation"

rm "$sandbox/themes/maho-lock/assets/icons/eye.svg"
if bash "$INSTALLER" status >/dev/null 2>&1; then
    fail "SDDM status accepted an incomplete installed vector set"
fi
pass "installed visual status detects incomplete staging"

bash "$INSTALLER" install >/dev/null
bash "$INSTALLER" status >/dev/null
pass "idempotent SDDM reinstall"

bash "$INSTALLER" uninstall >/dev/null
[ ! -e "$sandbox/config/90-maho-lock.conf" ] \
    || fail "SDDM selection survived uninstall"
[ ! -e "$sandbox/themes/maho-lock" ] \
    || fail "SDDM theme survived uninstall"
pass "recoverable managed SDDM uninstall"

printf 'PASS  Maho Lock SDDM persistence contracts\n'
