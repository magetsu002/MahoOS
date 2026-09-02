#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LINK="$ROOT/config/quickshell/maho-link"
BACKEND="$LINK/wifi.py"
EDGE="$ROOT/config/quickshell/maho-shell/EdgeBar.qml"
SIDE_EDGE="$ROOT/config/quickshell/maho-shell/SideEdgeBar.qml"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_file() {
    [ -r "$1" ] || fail "missing $1"
}

require_text() {
    local file="$1" text="$2" message="$3"
    grep -Fq -- "$text" "$file" || fail "$message"
}

echo "=== Maho Link packaged surface ==="
for file in \
    shell.qml \
    MahoLink.qml \
    MahoLinkMain.qml \
    MahoLinkTheme.qml \
    MahoLinkState.qml \
    MahoLinkNetworkRow.qml \
    MahoLinkSignal.qml \
    MahoLinkButton.qml \
    MahoLinkPassword.qml \
    MahoLinkManual.qml \
    MahoLinkDetails.qml \
    wifi.py
 do
    require_file "$LINK/$file"
 done
require_file "$ROOT/bin/maho-link"
echo "PASS"

echo "=== focused native overlay contract ==="
require_text "$LINK/shell.qml" 'WlrLayershell.namespace: "maho-link"' "Maho Link has no isolated layer-shell namespace"
require_text "$LINK/shell.qml" 'WlrLayershell.layer: WlrLayer.Overlay' "Maho Link is not an overlay surface"
require_text "$LINK/shell.qml" 'onClicked: root.closeOverlay()' "outside click does not close Maho Link"
require_text "$LINK/MahoLink.qml" 'Keys.onEscapePressed: root.closeRequested()' "Escape close missing"
require_text "$LINK/MahoLink.qml" 'text: "Wi-Fi"' "Wi-Fi title missing"
require_text "$LINK/MahoLink.qml" 'function stableAccent(source)' "adaptive accent clamp missing"
require_text "$LINK/MahoLinkTheme.qml" '/.cache/maho/theme/active.json' "Maho Link does not use authoritative Maho palette"
require_text "$LINK/MahoLinkTheme.qml" 'watchChanges: true' "Maho Link palette is not reactive"
if grep -RnsEi '\bbluetooth\b' "$LINK" --include='*.qml' --include='*.py'; then
    fail "Bluetooth UI/backend leaked into Wi-Fi-only Maho Link milestone"
fi
echo "PASS"

echo "=== narrow Edge hook contract ==="
require_text "$EDGE" 'Quickshell.env("MAHO_LINK_LAUNCHER")' "horizontal Edge lacks reversible Maho Link launcher override"
require_text "$EDGE" 'point.position.x <= 32' "horizontal Wi-Fi hit target is not isolated"
require_text "$SIDE_EDGE" 'Quickshell.env("MAHO_LINK_LAUNCHER")' "side Edge lacks reversible Maho Link launcher override"
require_text "$SIDE_EDGE" 'point.position.y <= 46' "side Wi-Fi hit target is not isolated"
require_text "$EDGE" 'edge.openRequested()' "existing horizontal Edge expansion path was removed"
require_text "$SIDE_EDGE" 'edge.openRequested()' "existing side Edge expansion path was removed"
echo "PASS"

echo "=== backend syntax ==="
python -m py_compile "$BACKEND"
bash -n "$ROOT/bin/maho-link"
echo "PASS"

echo "=== deterministic NetworkManager snapshot ==="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat >"$TMP/bin/nmcli" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

case "$*" in
  "-t -f WIFI general")
    echo "enabled"
    ;;
  "-t -e yes -f DEVICE,TYPE,STATE device status")
    echo "wlan0:wifi:connected"
    ;;
  "-t -e yes -f IN-USE,SSID,SIGNAL,SECURITY,FREQ device wifi list --rescan no")
    cat <<'SCAN'
*:Ashraf4G:91:WPA2:5180
:Guest\:Lab:61:WPA2:2412
:OpenCafe:44:--:2412
:CorpNet:80:WPA2 802.1X:5180
:Ashraf4G:52:WPA2:2412
SCAN
    ;;
  "-t -e yes -f IP4.ADDRESS,IP4.GATEWAY device show wlan0")
    cat <<'IP'
IP4.ADDRESS[1]:192.168.1.50/24
IP4.GATEWAY:192.168.1.1
IP
    ;;
  "device wifi rescan"|"radio wifi on"|"radio wifi off"|"device disconnect wlan0")
    :
    ;;
  --wait\ 20\ --ask\ device\ wifi\ connect\ *)
    printf '%s\n' "$*" >>"${FAKE_NMCLI_LOG:?}"
    IFS= read -r secret || true
    printf '%s\n' "$secret" >>"${FAKE_NMCLI_STDIN:?}"
    ;;
  --wait\ 20\ device\ wifi\ connect\ *)
    printf '%s\n' "$*" >>"${FAKE_NMCLI_LOG:?}"
    ;;
  *)
    echo "unexpected fake nmcli invocation: $*" >&2
    exit 64
    ;;
esac
EOF
chmod +x "$TMP/bin/nmcli"

export FAKE_NMCLI_LOG="$TMP/argv.log"
export FAKE_NMCLI_STDIN="$TMP/stdin.log"
: >"$FAKE_NMCLI_LOG"
: >"$FAKE_NMCLI_STDIN"
PATH="$TMP/bin:$PATH" python "$BACKEND" snapshot >"$TMP/snapshot.json"

python - "$TMP/snapshot.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data["available"] is True
assert data["enabled"] is True
assert data["device"] == "wlan0"
assert data["current"]["ssid"] == "Ashraf4G"
assert data["current"]["signal"] == 91
assert data["current"]["quality"] == "Excellent"
assert data["current"]["band"] == "5 GHz"
assert data["current"]["ipv4"] == "192.168.1.50/24"
assert data["current"]["gateway"] == "192.168.1.1"
rows = {row["ssid"]: row for row in data["networks"]}
assert "Ashraf4G" not in rows
assert rows["Guest:Lab"]["signal"] == 61
assert rows["OpenCafe"]["secured"] is False
assert rows["CorpNet"]["enterprise"] is True
PY
echo "PASS"

echo "=== password transport stays off argv ==="
printf 'correct horse battery staple\n' | PATH="$TMP/bin:$PATH" python "$BACKEND" action connect Ashraf4G >"$TMP/connect.json"
python - "$TMP/connect.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data["ok"] is True
PY
if grep -Fq 'correct horse battery staple' "$FAKE_NMCLI_LOG"; then
    fail "Wi-Fi password leaked into nmcli argv"
fi
grep -Fxq 'correct horse battery staple' "$FAKE_NMCLI_STDIN" || fail "Wi-Fi password was not delivered over stdin"
echo "PASS"

echo "Maho Link contracts passed."
