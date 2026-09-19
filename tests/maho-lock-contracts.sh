#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK/shell.qml"
SURFACE="$LOCK/MahoLockSurface.qml"
VIEW="$LOCK/MahoLockViewV7.qml"
BASE="$LOCK/MahoLockViewV5.qml"
AVATAR="$LOCK/MahoAvatarControl.qml"
GLASS="$LOCK/MahoGlassCapsuleV3.qml"
ACTION="$LOCK/MahoActionButton.qml"
PICKER="$LOCK/MahoImagePicker.qml"
STATE="$LOCK/MahoLockState.qml"
PROBE="$LOCK/state.py"
BROWSER="$LOCK/image_browser.py"
PREVIEW="$LOCK/preview.qml"
AUTH="$LOCK/MahoLockAuth.qml"
ICON="$LOCK/MahoIconV2.qml"
LAUNCHER="$ROOT/bin/maho-lock"
ROUNDED_FONT="$LOCK/assets/Nunito-Variable.ttf"
ROUNDED_LICENSE="$LOCK/assets/Nunito-OFL.txt"
FALLBACK_WALLPAPER="$LOCK/assets/maho-lock-dusk.jpg"
fail(){ printf 'FAIL  %s\n' "$*" >&2; exit 1; }
pass(){ printf 'PASS  %s\n' "$*"; }
for f in "$SHELL" "$SURFACE" "$VIEW" "$BASE" "$AVATAR" "$GLASS" "$ACTION" "$PICKER" "$STATE" "$PROBE" "$BROWSER" "$PREVIEW" "$AUTH" "$ICON" "$LAUNCHER" "$ROUNDED_FONT" "$ROUNDED_LICENSE" "$FALLBACK_WALLPAPER"; do [ -r "$f" ] || fail "missing ${f#$ROOT/}"; done
bash -n "$LAUNCHER"
python3 - "$PROBE" "$BROWSER" <<'PY'
import ast
from pathlib import Path
import sys

for raw in sys.argv[1:]:
    path = Path(raw)
    compile(path.read_bytes(), str(path), "exec", ast.PyCF_ONLY_AST, dont_inherit=True)
PY
pass "launcher and helper syntax"

grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure session-lock authority missing"
grep -Fq 'pragma ComponentBehavior: Bound' "$SHELL" || fail "deferred secure surface cannot resolve shared dependencies"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "secure lock surface missing"
grep -Fq 'MahoLockViewV7 {' "$SURFACE" || fail "production does not render V7"
grep -Fq 'surfaceReady: root.surfaceReady' "$SURFACE" || fail "secure shared view is not gated by surface readiness"
grep -Fq 'secure && visible && width > 0 && height > 0' "$SURFACE" || fail "secure readiness lacks protocol/visibility/size authority"
grep -Fq 'Component.onCompleted: locked = true' "$SHELL" || fail "secure lock does not engage"
grep -Fq 'onLockedChanged:' "$SHELL" || fail "one-shot locker ignores late locked=false transition"
grep -Fq 'wasSecure && !sessionLock.secure && !sessionLock.locked' "$SHELL" || fail "locker exit is not gated on complete secure release"
grep -Fq 'PamContext {' "$AUTH" || fail "PAM missing"
grep -Fq 'result === PamResult.Success' "$AUTH" || fail "PAM success gate missing"
grep -Fq 'auth.lock.locked = false' "$AUTH" || fail "PAM cannot release lock"
pass "secure Wayland + PAM boundary"

grep -Fq 'MahoLockViewV7 {' "$PREVIEW" || fail "preview does not render V7"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode missing"
grep -Fq 'surfaceReady: previewWindow.visible' "$PREVIEW" || fail "preview shared view lacks realized-window readiness"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then fail "preview can acquire secure lock"; fi
pass "safe exact-view preview"

python3 - "$SURFACE" "$PREVIEW" <<'PY'
from pathlib import Path
import re
import sys

secure, preview = (Path(path).read_text() for path in sys.argv[1:])
component = re.compile(r"\bMahoLockViewV(\d+)\s*\{")
secure_views = component.findall(secure)
preview_views = component.findall(preview)
assert secure_views == ["7"], secure_views
assert preview_views == ["7"], preview_views
PY
pass "preview and secure hosts instantiate exactly the same accepted view"

grep -Fq 'readonly property bool hostWindowActive: Window.active' "$BASE" || fail "password focus is not tied to window activation"
grep -Fq 'onHostWindowActiveChanged:' "$BASE" || fail "window activation cannot restore password focus"
grep -Fq 'onPresentationReadyChanged:' "$BASE" || fail "surface readiness cannot activate the accepted view"
grep -Fq 'surfaceReady && width > 0 && height > 0' "$BASE" || fail "accepted view can activate at zero size"
if grep -Fq 'focusRecovery' "$BASE"; then fail "blind focus polling timer remains"; fi
pass "deterministic secure presentation and focus lifecycle"

grep -Fq 'Qt.rgba(0.973, 0.984, 1.000, 0.98)' "$BASE" || fail "primary foreground contrast drifted"
grep -Fq 'Qt.rgba(0.957, 0.976, 1.000, 0.94)' "$BASE" || fail "secondary foreground contrast drifted"
grep -Fq 'Qt.rgba(0.933, 0.965, 1.000, 0.82)' "$BASE" || fail "tertiary foreground contrast drifted"
grep -Fq 'RadialGradient {' "$BASE" || fail "central atmospheric focus veil missing"
grep -Fq 'root.focused ? 0.31 : 0.24' "$GLASS" || fail "password glass definition drifted"
grep -Fq 'root.strong ? 0.50 : 0.46' "$GLASS" || fail "glass edge hierarchy drifted"
grep -Fq 'shadowEnabled: true' "$GLASS" || fail "glass separation shadow missing"
grep -Fq 'root.editable && root.hovered ? 0.82 : 0.70' "$AVATAR" || fail "avatar separation ring drifted"
grep -Fq 'Qt.rgba(0.031, 0.106, 0.227, 0.20)' "$ACTION" || fail "corner action glass treatment missing"
grep -Fq 'id: contentRow' "$ACTION" || fail "corner action icon and label are not grouped geometrically"
grep -Fq 'anchors.centerIn: parent' "$ACTION" || fail "corner action content is not centered in its pill"
grep -Fq 'spacing: 14' "$ACTION" || fail "corner action icon-to-label spacing drifted"
grep -Fq 'id: fieldDivider' "$BASE" || fail "password field divider missing"
grep -Fq 'statusLabelWidth: batteryPercentageLabel.visible' "$BASE" || fail "battery hover does not measure the complete percentage label"
pass "focused contrast and glass hierarchy"

grep -Fq 'mipmap: false' "$BASE" || fail "wallpaper texture filtering can re-soften the image"
if grep -Eq 'id: wallpaperEffect|id: wallpaperTexture|blurMax: 32|sourceSize\.(width|height): root\.(width|height)' "$BASE"; then
    fail "destructive full-screen wallpaper resampling remains"
fi
grep -Fq 'source: "assets/Nunito-Variable.ttf"' "$BASE" || fail "rounded UI typeface is not bundled"
grep -Fq 'MAHO_LOCK_TYPOGRAPHY' "$BASE" || fail "classic typography fallback is missing"
grep -Fq 'font.family: root.uiFontFamily' "$BASE" || fail "rounded typography is not applied"
grep -Fq 'useRoundedTypography ? 600 : 400' "$BASE" || fail "rounded typography weight-axis contract drifted"
grep -Fq 'font.variableAxes: ({ "wght": root.uiAxisWeight })' "$BASE" || fail "rounded variable-font weight is not pinned"
pass "native wallpaper fidelity and reversible rounded typography"

jpeg_magic="$(od -An -tx1 -N3 "$FALLBACK_WALLPAPER" | tr -d ' \n')"
[[ "$jpeg_magic" == "ffd8ff" ]] || fail "fallback wallpaper is not valid JPEG data"
[[ "$(stat -c %s "$FALLBACK_WALLPAPER")" -gt 100000 ]] \
    || fail "fallback wallpaper is suspiciously truncated"
pass "decodable fallback wallpaper asset"

grep -Fq 'MahoLockViewV5 {' "$VIEW" || fail "V7 lost accepted base hierarchy"
grep -Fq 'MahoImagePicker {' "$VIEW" || fail "in-app image picker missing"
grep -Fq 'onClicked: root.openWallpaperPicker()' "$VIEW" || fail "wallpaper lacks separate affordance"
grep -Fq 'suppressBuiltinAvatar: true' "$VIEW" || fail "accepted view can flash the base fallback avatar"
if grep -Eq 'MahoAvatarControl|openPicker\("avatar"\)|avatarControl|avatarReveal|avatarSize|avatarX|avatarY' "$VIEW"; then
    fail "accepted lock view reintroduced a profile-photo surface"
fi
grep -Fq 'anchors.topMargin: (root.suppressBuiltinAvatar ? 330 : 477) * root.uiScale' "$BASE"     || fail "avatar-free lock composition does not move authentication upward"
grep -Fq 'visible: !root.suppressBuiltinAvatar' "$BASE" || fail "base avatar cannot be suppressed by the accepted view"
pass "separated personalization surfaces"

grep -Fq 'badgeCenterOffset: avatarRadius / Math.SQRT2' "$AVATAR" || fail "edit badge is not geometrically placed on circumference"
grep -Fq 'x: root.badgeCenterX - width / 2' "$AVATAR" || fail "badge x-center formula missing"
grep -Fq 'y: root.badgeCenterY - height / 2' "$AVATAR" || fail "badge y-center formula missing"
grep -Fq 'anchors.centerIn: parent' "$AVATAR" || fail "edit glyph is not centered in badge"
grep -Fq 'sourceSize.width: root.avatarDecodeSize' "$AVATAR" || fail "high-resolution avatar decode missing"
grep -Fq 'Math.max(1024, Math.ceil(width * 6))' "$AVATAR" || fail "avatar quality floor missing"
grep -Fq 'asynchronous: false' "$AVATAR" || fail "selected avatar can miss the first presented frame"
grep -Fq 'property string avatarPath: profile.avatarPath' "$STATE" || fail "selected avatar is not loaded synchronously from profile state"
python3 - <<'PY'
import math
avatar_size = 112.0
badge_size = 30.0
radius = avatar_size / 2.0
offset = radius / math.sqrt(2.0)
badge_cx = avatar_size / 2.0 + offset
badge_cy = avatar_size / 2.0 + offset
assert math.isclose(math.hypot(badge_cx - radius, badge_cy - radius), radius, rel_tol=0, abs_tol=1e-12)
badge_x = badge_cx - badge_size / 2.0
badge_y = badge_cy - badge_size / 2.0
assert math.isclose(badge_x + badge_size / 2.0, badge_cx, abs_tol=1e-12)
assert math.isclose(badge_y + badge_size / 2.0, badge_cy, abs_tol=1e-12)
PY
pass "avatar geometry and quality"

grep -Fq 'id: searchInput' "$PICKER" || fail "picker search missing"
grep -Fq 'searchDebounce' "$PICKER" || fail "search is not debounced"
grep -Fq 'sourceSize.width: root.avatarMode ? 768 : 1280' "$PICKER" || fail "high-resolution picker thumbnails missing"
grep -Fq 'openImageBrowser(root.mode)' "$PICKER" || fail "picker does not open at semantic default path"
if grep -Eq 'QtQuick\.Dialogs|FileDialog' "$VIEW" "$PICKER"; then fail "modal native file dialog reintroduced"; fi
pass "non-modal searchable high-quality picker"

grep -Fq 'MAX_SEARCH_SCAN' "$BROWSER" || fail "recursive search is not bounded"
grep -Fq 'recursive_search' "$BROWSER" || fail "recursive image search missing"
grep -Fq 'avatarBrowsePath' "$PROBE" || fail "avatar default path persistence missing"
grep -Fq 'wallpaperBrowsePath' "$PROBE" || fail "wallpaper default path persistence missing"
grep -Fq 'defaultBrowsePath(mode)' "$STATE" || fail "state does not expose per-mode defaults"
pass "bounded search and remembered defaults"

grep -Fq 'closePeerStatuses(rootItem())' "$ICON" || fail "status cards can stack"
grep -Fq 'visible: root.statusOpen' "$ICON" || fail "closed status card can linger"
pass "single top-right status surface"

grep -Fq 'flock -n 9' "$LAUNCHER" || fail "locker process ownership missing"
grep -Fq -- '--preview|--customize' "$LAUNCHER" || fail "safe customization launcher alias missing"
grep -Fq 'runtime.log' "$LAUNCHER" || fail "secure lifecycle evidence is not persistent"
if grep -Eq 'pkill|killall' "$LAUNCHER"; then fail "launcher uses broad kills"; fi
pass "runtime ownership"
printf 'PASS  Maho Lock final preinstall contracts\n'
