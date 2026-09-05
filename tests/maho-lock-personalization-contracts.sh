#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK="$ROOT/config/quickshell/maho-lock"
VIEW="$LOCK/MahoLockViewV7.qml"
PICKER="$LOCK/MahoImagePicker.qml"
STATE_QML="$LOCK/MahoLockState.qml"
STATE_PY="$LOCK/state.py"
BROWSER_PY="$LOCK/image_browser.py"
fail(){ printf 'FAIL  %s\n' "$*" >&2; exit 1; }
pass(){ printf 'PASS  %s\n' "$*"; }
for f in "$VIEW" "$PICKER" "$STATE_QML" "$STATE_PY" "$BROWSER_PY"; do [ -r "$f" ] || fail "missing $f"; done

if grep -Eq 'QtQuick\.Dialogs|FileDialog' "$VIEW" "$PICKER"; then fail "modal native file dialog returned"; fi
grep -Fq 'onEditRequested: root.openPicker("avatar")' "$VIEW" || fail "avatar click not direct"
grep -Fq 'onClicked: root.openPicker("wallpaper")' "$VIEW" || fail "wallpaper not separate"
grep -Fq 'id: searchInput' "$PICKER" || fail "search input missing"
grep -Fq 'Search images' "$PICKER" || fail "search affordance missing"
grep -Fq 'root.lockState.openImageBrowser(root.mode)' "$PICKER" || fail "semantic default folder not used"
grep -Fq 'root.lockState.browseImages(' "$PICKER" || fail "search/navigation not routed through state"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/home/Pictures/Portraits/Nested" "$TMP/home/Pictures/Wallpapers/Space" "$TMP/state" "$TMP/outside"
printf avatar > "$TMP/home/Pictures/Portraits/me-avatar.png"
printf nested > "$TMP/home/Pictures/Portraits/Nested/other-profile.webp"
printf wall > "$TMP/home/Pictures/Wallpapers/Space/nebula-wallpaper.jpg"
printf ignore > "$TMP/home/Pictures/Portraits/notes.txt"
printf outside > "$TMP/outside/secret.png"
ln -s "$TMP/outside" "$TMP/home/Pictures/Portraits/outside-link"

HOME="$TMP/home" python3 "$BROWSER_PY" "$TMP/home/Pictures" avatar > "$TMP/search.json"
python3 - "$TMP/search.json" "$TMP/home/Pictures/Portraits/me-avatar.png" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
paths={e['path'] for e in p['entries']}
assert sys.argv[2] in paths
assert all(e['isDir'] is False for e in p['entries'])
assert p['query']=='avatar'
PY

HOME="$TMP/home" python3 "$BROWSER_PY" "$TMP/home/Pictures/Portraits" > "$TMP/browse.json"
python3 - "$TMP/browse.json" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
names={e['name'] for e in p['entries']}
assert 'Nested' in names
assert 'me-avatar.png' in names
assert 'notes.txt' not in names
assert 'outside-link' not in names
PY

HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" python3 "$STATE_PY" --set-avatar "$TMP/home/Pictures/Portraits/me-avatar.png" > "$TMP/avatar.json"
HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" python3 "$STATE_PY" --set-wallpaper "$TMP/home/Pictures/Wallpapers/Space/nebula-wallpaper.jpg" > "$TMP/wall.json"
HOME="$TMP/home" XDG_STATE_HOME="$TMP/state" python3 "$STATE_PY" > "$TMP/ambient.json"
python3 - "$TMP/ambient.json" "$TMP/home/Pictures/Portraits" "$TMP/home/Pictures/Wallpapers/Space" <<'PY'
import json,sys
from pathlib import Path
p=json.loads(Path(sys.argv[1]).read_text())
assert p['avatarBrowsePath']==sys.argv[2]
assert p['wallpaperBrowsePath']==sys.argv[3]
PY

grep -Fq 'property string avatarBrowsePath' "$STATE_QML" || fail "avatar browse state missing"
grep -Fq 'property string wallpaperBrowsePath' "$STATE_QML" || fail "wallpaper browse state missing"
grep -Fq 'function openImageBrowser(mode)' "$STATE_QML" || fail "mode-aware browser opener missing"
grep -Fq 'requestedBrowserQuery' "$STATE_QML" || fail "queued search state missing"
grep -Fq 'SwitchToGreeter' "$STATE_PY" || fail "SDDM switch-user support missing"

python3 - "$STATE_PY" <<'PY'
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("maho_lock_state", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

original_which = module.shutil.which
original_run = module.run
try:
    module.shutil.which = lambda name: "/usr/bin/busctl" if name == "busctl" else None
    module.run = lambda args: "b true\n" if "get-property" in args else ""
    command = module.switch_user_command()
finally:
    module.shutil.which = original_which
    module.run = original_run

assert command == [
    "/usr/bin/busctl",
    "--system",
    "call",
    "org.freedesktop.DisplayManager",
    "/org/freedesktop/DisplayManager/Seat0",
    "org.freedesktop.DisplayManager.Seat",
    "SwitchToGreeter",
]
PY
pass "separate PFP/wallpaper pickers remember defaults and provide bounded recursive search"
