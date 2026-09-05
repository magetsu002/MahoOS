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
python3 -m py_compile "$PROBE" "$BROWSER"
pass "launcher and helper syntax"

grep -Fq 'WlSessionLock {' "$SHELL" || fail "secure session-lock authority missing"
grep -Fq 'WlSessionLockSurface {' "$SURFACE" || fail "secure lock surface missing"
grep -Fq 'MahoLockViewV7 {' "$SURFACE" || fail "production does not render V7"
grep -Fq 'Component.onCompleted: locked = true' "$SHELL" || fail "secure lock does not engage"
grep -Fq 'PamContext {' "$AUTH" || fail "PAM missing"
grep -Fq 'result === PamResult.Success' "$AUTH" || fail "PAM success gate missing"
grep -Fq 'auth.lock.locked = false' "$AUTH" || fail "PAM cannot release lock"
pass "secure Wayland + PAM boundary"

grep -Fq 'MahoLockViewV7 {' "$PREVIEW" || fail "preview does not render V7"
grep -Fq 'previewMode: true' "$PREVIEW" || fail "preview mode missing"
if grep -Eq 'WlSessionLock|PamContext' "$PREVIEW"; then fail "preview can acquire secure lock"; fi
pass "safe exact-view preview"

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
if grep -Eq 'pkill|killall' "$LAUNCHER"; then fail "launcher uses broad kills"; fi
pass "runtime ownership"
printf 'PASS  Maho Lock final preinstall contracts\n'
