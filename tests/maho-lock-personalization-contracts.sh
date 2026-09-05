#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ICON="$ROOT/config/quickshell/maho-lock/MahoIconV2.qml"
VIEW="$ROOT/config/quickshell/maho-lock/MahoLockViewV6.qml"
STATE_QML="$ROOT/config/quickshell/maho-lock/MahoLockState.qml"
STATE_PY="$ROOT/config/quickshell/maho-lock/state.py"
BROWSER_PY="$ROOT/config/quickshell/maho-lock/image_browser.py"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

pass() {
    printf 'PASS  %s\n' "$*"
}

for file in "$ICON" "$VIEW" "$STATE_QML" "$STATE_PY" "$BROWSER_PY"; do
    [ -r "$file" ] || fail "missing $file"
done

grep -Fq 'statusParticipant' "$ICON" || fail "status controls no longer expose peer identity"
grep -Fq 'closePeerStatuses(rootItem())' "$ICON" || fail "opening one status no longer closes peers"
grep -Fq 'visible: root.statusOpen' "$ICON" || fail "closed status cards can linger and stack"

if grep -Eq '^import QtQuick\.Dialogs|^[[:space:]]*FileDialog[[:space:]]*\{' "$VIEW"; then
    fail "overlay lock preview can still launch modal native file dialogs"
fi
grep -Fq 'onClicked: root.openPicker("avatar")' "$VIEW" \
    || fail "clicking the profile photo does not directly enter profile-photo selection"
grep -Fq 'onClicked: root.openPicker("wallpaper")' "$VIEW" \
    || fail "wallpaper selection is not a separate control"
grep -Fq 'text: "Wallpaper"' "$VIEW" \
    || fail "separate wallpaper affordance missing"
grep -Fq 'text: "Choose profile photo"' "$VIEW" \
    || fail "profile picker title missing"
grep -Fq 'text: "Choose lock wallpaper"' "$VIEW" \
    || fail "wallpaper picker title missing"
grep -Fq 'root.lockState.setAvatar(path)' "$VIEW" \
    || fail "profile selection does not reach avatar state authority"
grep -Fq 'root.lockState.setLockWallpaper(path)' "$VIEW" \
    || fail "wallpaper selection does not reach wallpaper state authority"
grep -Fq 'root.lockState.browseImages(path)' "$VIEW" \
    || fail "in-app picker cannot navigate folders"

grep -Fq 'function browseImages(path)' "$STATE_QML" \
    || fail "lock state does not expose in-app file browser"
grep -Fq 'imageBrowserProcess' "$STATE_QML" \
    || fail "in-app browser process missing"
grep -Fq 'image_browser.py' "$STATE_QML" \
    || fail "lock state does not call bounded browser backend"
grep -Fq 'function setLockWallpaper(path)' "$STATE_QML" \
    || fail "wallpaper persistence API missing"

grep -Fq 'IMAGE_EXTENSIONS' "$BROWSER_PY" || fail "browser does not filter images"
grep -Fq 'MAX_ENTRIES' "$BROWSER_PY" || fail "browser listing is not bounded"
grep -Fq 'inside_home' "$BROWSER_PY" || fail "browser is not constrained to the user home tree"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/home/Pictures/Sub" "$TMP/state" "$TMP/outside"
printf 'avatar' > "$TMP/home/Pictures/avatar.png"
printf 'wall' > "$TMP/home/Pictures/wall.jpg"
printf 'ignore' > "$TMP/home/Pictures/notes.txt"
printf 'nested' > "$TMP/home/Pictures/Sub/nested.webp"
printf 'outside' > "$TMP/outside/outside.png"
ln -s "$TMP/outside" "$TMP/home/Pictures/outside-link"

HOME="$TMP/home" python3 "$BROWSER_PY" "$TMP/home/Pictures" > "$TMP/browser.json"

python3 - "$TMP/browser.json" "$TMP/home/Pictures" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
assert payload["path"] == sys.argv[2]
names = {entry["name"] for entry in payload["entries"]}
assert "Sub" in names
assert "avatar.png" in names
assert "wall.jpg" in names
assert "notes.txt" not in names
assert "outside-link" not in names
PY

HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" \
    python3 "$STATE_PY" --set-wallpaper "$TMP/home/Pictures/wall.jpg" \
    > "$TMP/set-wallpaper.json"

grep -Fq '"ok":true' "$TMP/set-wallpaper.json" \
    || fail "explicit wallpaper selection did not persist"

HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" \
    python3 "$STATE_PY" --set-avatar "$TMP/home/Pictures/avatar.png" \
    > "$TMP/set-avatar.json"

grep -Fq '"ok":true' "$TMP/set-avatar.json" \
    || fail "explicit avatar selection did not persist"

python3 - "$TMP/state/maho/lock/profile.json" "$TMP/home/Pictures/avatar.png" "$TMP/home/Pictures/wall.jpg" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
assert payload.get("avatarPath") == sys.argv[2]
assert payload.get("wallpaperPath") == sys.argv[3]
PY

pass "single status surface and non-modal separated personalization are locked by contract"
