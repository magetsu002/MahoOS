#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ICON="$ROOT/config/quickshell/maho-lock/MahoIconV2.qml"
VIEW="$ROOT/config/quickshell/maho-lock/MahoLockViewV6.qml"
STATE_QML="$ROOT/config/quickshell/maho-lock/MahoLockState.qml"
STATE_PY="$ROOT/config/quickshell/maho-lock/state.py"

fail() {
    printf 'FAIL  %s\n' "$*" >&2
    exit 1
}

pass() {
    printf 'PASS  %s\n' "$*"
}

for file in "$ICON" "$VIEW" "$STATE_QML" "$STATE_PY"; do
    [ -r "$file" ] || fail "missing $file"
done

grep -Fq 'statusParticipant' "$ICON" || fail "status controls no longer expose peer identity"
grep -Fq 'closePeerStatuses(rootItem())' "$ICON" || fail "opening one status no longer closes peers"
grep -Fq 'visible: root.statusOpen' "$ICON" || fail "closed status cards can linger and stack"

grep -Fq 'import QtQuick.Dialogs' "$VIEW" || fail "native image file dialog import missing"
grep -Fq 'id: avatarFileDialog' "$VIEW" || fail "profile-photo file picker missing"
grep -Fq 'id: wallpaperFileDialog' "$VIEW" || fail "wallpaper file picker missing"
grep -Fq 'text: "Choose photo…"' "$VIEW" || fail "clear choose-photo action missing"
grep -Fq 'text: "Choose wallpaper…"' "$VIEW" || fail "clear choose-wallpaper action missing"
grep -Fq 'text: "Shuffle wallpaper"' "$VIEW" || fail "wallpaper shuffle action missing"
grep -Fq 'root.lockState.setLockWallpaper(path)' "$VIEW" || fail "selected wallpaper is not handed to state authority"

grep -Fq 'function setLockWallpaper(path)' "$STATE_QML" || fail "wallpaper persistence API missing"
grep -Fq 'function shuffleLockWallpaper()' "$STATE_QML" || fail "temporary wallpaper shuffle API missing"
grep -Fq 'wallpaperWriteProcess' "$STATE_QML" || fail "wallpaper persistence process missing"

grep -Fq '"--set-wallpaper"' "$STATE_PY" || fail "state backend cannot persist explicit wallpaper"
grep -Fq '"--shuffle-wallpaper"' "$STATE_PY" || fail "state backend cannot shuffle wallpaper independently"
grep -Fq 'savedWallpaperPath' "$STATE_PY" || fail "saved wallpaper is not restored into ambient state"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$TMP/home/Pictures" "$TMP/state"
printf 'avatar' > "$TMP/home/Pictures/avatar.png"
printf 'wall' > "$TMP/home/Pictures/wall.jpg"

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

HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" \
    python3 "$STATE_PY" --pick-wallpaper \
    > "$TMP/pick-wallpaper.json"

grep -Fq "$TMP/home/Pictures/wall.jpg" "$TMP/pick-wallpaper.json" \
    || fail "saved wallpaper is not authoritative on next lock process"

python3 - "$TMP/state/maho/lock/profile.json" "$TMP/home/Pictures/avatar.png" "$TMP/home/Pictures/wall.jpg" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text())
assert payload.get("avatarPath") == sys.argv[2]
assert payload.get("wallpaperPath") == sys.argv[3]
PY

pass "single status surface and explicit file personalization are locked by contract"
