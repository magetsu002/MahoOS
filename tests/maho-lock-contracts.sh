#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/config/quickshell/maho-lock"
SHELL="$LOCK/shell.qml"
SURFACE="$LOCK/MahoLockSurface.qml"
VIEW="$LOCK/MahoLockViewV7.qml"
BASE="$LOCK/MahoLockViewV5.qml"
AVATAR="$LOCK/MahoAvatarControl.qml"
PICKER="$LOCK/MahoImagePicker.qml"
STATE="$LOCK/MahoLockState.qml"
PROBE="$LOCK/state.py"
BROWSER="$LOCK/image_browser.py"
PREVIEW="$LOCK/preview.qml"
AUTH="$LOCK/MahoLockAuth.qml"
ICON="$LOCK/MahoIconV2.qml"
LAUNCHER="$ROOT/bin/maho-lock"
fail(){ printf 'FAIL  %s\n' "$*" >&2; exit 1; }
pass(){ printf 'PASS  %s\n' "$*"; }
for f in "$SHELL" "$SURFACE" "$VIEW" "$BASE" "$AVATAR" "$PICKER" "$STATE" "$PROBE" "$BROWSER" "$PREVIEW" "$AUTH" "$ICON" "$LAUNCHER"; do [ -r "$f" ] || fail "missing ${f#$ROOT/}"; done
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

grep -Fq 'MahoLockViewV5 {' "$VIEW" || fail "V7 lost accepted base hierarchy"
grep -Fq 'MahoAvatarControl {' "$VIEW" || fail "geometric avatar control missing"
grep -Fq 'MahoImagePicker {' "$VIEW" || fail "in-app image picker missing"
grep -Fq 'onEditRequested: root.openPicker("avatar")' "$VIEW" || fail "PFP click not dedicated to PFP"
grep -Fq 'onClicked: root.openPicker("wallpaper")' "$VIEW" || fail "wallpaper lacks separate affordance"
pass "separated personalization surfaces"

grep -Fq 'badgeCenterOffset: avatarRadius / Math.SQRT2' "$AVATAR" || fail "edit badge is not geometrically placed on circumference"
grep -Fq 'x: root.badgeCenterX - width / 2' "$AVATAR" || fail "badge x-center formula missing"
grep -Fq 'y: root.badgeCenterY - height / 2' "$AVATAR" || fail "badge y-center formula missing"
grep -Fq 'anchors.centerIn: parent' "$AVATAR" || fail "edit glyph is not centered in badge"
grep -Fq 'sourceSize.width: root.avatarDecodeSize' "$AVATAR" || fail "high-resolution avatar decode missing"
grep -Fq 'Math.max(1024, Math.ceil(width * 6))' "$AVATAR" || fail "avatar quality floor missing"
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
grep -Fq 'runtime.log' "$LAUNCHER" || fail "secure lifecycle evidence is not persistent"
if grep -Eq 'pkill|killall' "$LAUNCHER"; then fail "launcher uses broad kills"; fi
pass "runtime ownership"
printf 'PASS  Maho Lock final preinstall contracts\n'
