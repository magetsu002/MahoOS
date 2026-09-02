#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LINK="$ROOT/config/quickshell/maho-link"
NOTIFY="$ROOT/config/quickshell/maho-notify"
BACKEND="$LINK/wifi.py"
BT_BACKEND="$LINK/bluetooth.py"
EDGE="$ROOT/config/quickshell/maho-shell/EdgeBar.qml"
SIDE_EDGE="$ROOT/config/quickshell/maho-shell/SideEdgeBar.qml"
SHELL="$ROOT/config/quickshell/maho-shell/shell.qml"

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
    BluetoothState.qml \
    BluetoothMain.qml \
    BluetoothDeviceRow.qml \
    BluetoothPairing.qml \
    BluetoothDetails.qml \
    BluetoothForgetConfirmation.qml \
    wifi.py \
    bluetooth.py
 do
    require_file "$LINK/$file"
 done
require_file "$ROOT/bin/maho-link"
echo "PASS"

echo "=== focused native overlay contract ==="
require_text "$LINK/shell.qml" 'WlrLayershell.namespace: "maho-link"' "Maho Link has no isolated layer-shell namespace"
require_text "$LINK/shell.qml" 'WlrLayershell.layer: WlrLayer.Overlay' "Maho Link is not an overlay surface"
require_text "$LINK/shell.qml" 'onClicked: root.closeOverlay()' "outside click does not close Maho Link"
require_text "$LINK/shell.qml" 'root.overlayOpen ? 0.16 : 0' "overlay backdrop separation regressed"
require_text "$LINK/MahoLink.qml" 'Keys.onEscapePressed: root.closeRequested()' "Escape close missing"
require_text "$LINK/MahoLink.qml" '? "Wi-Fi"' "Wi-Fi title missing"
require_text "$LINK/MahoLink.qml" 'function stableAccent(source)' "adaptive accent clamp missing"
require_text "$LINK/MahoLink.qml" 'readonly property bool compactMain:' "compact empty-network layout missing"
require_text "$LINK/MahoLink.qml" 'readonly property color shellFill:' "dense shell material missing"
require_text "$LINK/MahoLink.qml" '0.985)' "shell material is too transparent"
require_text "$LINK/MahoLink.qml" 'theme.alpha(theme.outline, 0.065)' "residual shell edge is too prominent"
require_text "$LINK/MahoLink.qml" 'anchors.leftMargin: 20' "left chrome alignment drifted"
require_text "$LINK/MahoLink.qml" 'anchors.rightMargin: 20' "right chrome alignment drifted"
require_text "$LINK/MahoLinkMain.qml" '"No other networks found"' "connected empty-state copy missing"
require_text "$LINK/MahoLinkMain.qml" 'root.height - 151' "empty/list height no longer follows panel geometry"
require_text "$LINK/MahoLinkState.qml" 'id: statusClearTimer' "transient success feedback timer missing"
require_text "$LINK/MahoLinkState.qml" 'interval: 1500' "success feedback no longer clears promptly"
require_text "$LINK/MahoLinkTheme.qml" '/.cache/maho/theme/active.json' "Maho Link does not use authoritative Maho palette"
require_text "$LINK/MahoLinkTheme.qml" 'watchChanges: true' "Maho Link palette is not reactive"
require_text "$LINK/shell.qml" 'MAHO_LINK_MODE' "Maho Link cannot select a focused connectivity state"
require_text "$LINK/MahoLink.qml" 'section === "bluetooth"' "Bluetooth is not a state of the existing Maho Link shell"
require_text "$LINK/BluetoothMain.qml" 'Bluetooth is Off' "Bluetooth off state missing"
require_text "$LINK/BluetoothMain.qml" 'No Paired Devices' "Bluetooth empty paired-device state missing"
require_text "$LINK/BluetoothPairing.qml" 'cancelPairing(root.device)' "pairing Cancel does not reach BlueZ"
require_text "$LINK/BluetoothForgetConfirmation.qml" 'Forget Device' "forget confirmation state missing"
echo "PASS"

echo "=== BlueZ authority and privacy contract ==="
require_text "$BT_BACKEND" 'org.freedesktop.DBus.ObjectManager' "Bluetooth backend does not use structured BlueZ ObjectManager data"
require_text "$BT_BACKEND" 'org.bluez.Adapter1' "Bluetooth adapter interface missing"
require_text "$BT_BACKEND" 'org.bluez.Device1' "Bluetooth device interface missing"
require_text "$BT_BACKEND" 'org.bluez.Battery1' "BlueZ Battery1 support missing"
require_text "$BT_BACKEND" 'StartDiscovery' "BlueZ discovery action missing"
require_text "$BT_BACKEND" 'RemoveDevice' "BlueZ forget action missing"
require_text "$LINK/BluetoothState.qml" 'org.bluez.Device1", "CancelPairing"' "BlueZ pairing cancellation missing"
require_text "$LINK/BluetoothState.qml" 'busctl", "--system", "monitor", "org.bluez"' "Bluetooth state is not driven by BlueZ signals"
if grep -RnsF 'bluetoothctl' "$LINK" --include='*.qml'; then
    fail "Maho Link Bluetooth QML must not drive bluetoothctl"
fi
if grep -nsE '(subprocess\.(run|Popen).*bluetoothctl|\[[^]]*["'"']bluetoothctl["'"'])' "$BT_BACKEND"; then
    fail "Maho Link Bluetooth backend must not execute bluetoothctl"
fi
if grep -RnsE 'WH-1000XM5|Magic Keyboard|Magic Trackpad|AirPods Pro|MX Master 3S|Echo Dot|Soundcore Liberty|WH-CH720N' "$LINK" --include='*.qml' --include='*.py'; then
    fail "illustrative Bluetooth concept device data was hardcoded"
fi
if grep -RnsE 'Firmware 2\.0\.1|100% Battery' "$LINK" --include='*.qml' --include='*.py'; then
    fail "illustrative Bluetooth metadata was hardcoded"
fi
echo "PASS"

echo "=== Edge-aware transient placement contract ==="
require_text "$LINK/shell.qml" '/quickshell/by-shell/maho-shell/dock.json' "Maho Link does not observe authoritative Edge placement"
require_text "$LINK/shell.qml" 'readonly property real dockPosition:' "Maho Link ignores along-edge position"
require_text "$LINK/shell.qml" 'dockPosition > 0.5' "Maho Link cannot detect a top/bottom Edge on the right half"
require_text "$LINK/shell.qml" 'if (dockOccupiesRightSide)' "Maho Link does not move opposite the Edge location"
require_text "$LINK/shell.qml" 'x: root.surfaceX(overlay.width, width, 24)' "Maho Link placement is no longer derived from Edge location"
require_text "$NOTIFY/shell.qml" '/quickshell/by-shell/maho-shell/dock.json' "Maho Notify does not observe authoritative Edge placement"
require_text "$NOTIFY/shell.qml" 'readonly property real dockPosition:' "Maho Notify ignores along-edge position"
require_text "$NOTIFY/shell.qml" 'dockPosition > 0.5' "Maho Notify cannot detect a top/bottom Edge on the right half"
require_text "$NOTIFY/shell.qml" 'if (dockOccupiesRightSide)' "Maho Notify does not move opposite the Edge location"
require_text "$NOTIFY/shell.qml" 'x: root.surfaceX(overlay.width, width, 18)' "notification popup placement is not Edge-aware"
require_text "$NOTIFY/shell.qml" 'x: root.surfaceX(centerOverlay.width, width, 18)' "notification center placement is not Edge-aware"
require_text "$LINK/shell.qml" 'watchChanges: true' "Maho Link does not react to Edge moves"
require_text "$NOTIFY/shell.qml" 'watchChanges: true' "Maho Notify does not react to Edge moves"
echo "PASS"

echo "=== narrow Edge hook contract ==="
require_text "$EDGE" 'Quickshell.env("MAHO_LINK_LAUNCHER")' "horizontal Edge lacks reversible Maho Link launcher override"
require_text "$EDGE" 'point.position.x <= 32' "horizontal Wi-Fi hit target is not isolated"
require_text "$SIDE_EDGE" 'Quickshell.env("MAHO_LINK_LAUNCHER")' "side Edge lacks reversible Maho Link launcher override"
require_text "$SIDE_EDGE" 'point.position.y <= 46' "side Wi-Fi hit target is not isolated"
require_text "$EDGE" 'edge.openRequested()' "existing horizontal Edge expansion path was removed"
require_text "$SIDE_EDGE" 'edge.openRequested()' "existing side Edge expansion path was removed"
require_text "$SHELL" 'Quickshell.execDetached(["bash", Quickshell.env("HOME") + "/.local/bin/maho-link"])' "expanded Edge Wi-Fi card does not route to Maho Link"
require_text "$SHELL" '"bluetooth"' "expanded Edge Bluetooth card does not route to Maho Link Bluetooth"
if grep -Fq 'kitty -e nmtui' "$SHELL"; then
    fail "legacy nmtui Wi-Fi routing remains in Maho Edge"
fi
if grep -Fq 'kitty -e bluetoothctl' "$SHELL"; then
    fail "legacy terminal Bluetooth routing remains in Maho Edge"
fi
echo "PASS"

echo "=== backend syntax ==="
python -m py_compile "$BACKEND" "$BT_BACKEND"
bash -n "$ROOT/bin/maho-link"
require_text "$BACKEND" '"--rescan", "auto"' "snapshot no longer permits NetworkManager to refresh stale discovery"
require_text "$ROOT/bin/maho-link" 'wifi|bluetooth' "Maho Link launcher does not constrain focused modes"
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
  "-t -e yes -f IN-USE,SSID,SIGNAL,SECURITY,FREQ device wifi list --rescan auto")
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

echo "=== deterministic BlueZ ObjectManager snapshot ==="
cat >"$TMP/bin/busctl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_BUSCTL_LOG:?}"

if [ "$*" = "--system --json=short call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects" ]; then
cat <<'JSON'
{"type":"a{oa{sa{sv}}}","data":[{"/org/bluez/hci0":{"org.bluez.Adapter1":{"Powered":{"type":"b","data":true},"Discovering":{"type":"b","data":true}}},"/org/bluez/hci0/dev_AA_BB_CC_DD_EE_01":{"org.bluez.Device1":{"Adapter":{"type":"o","data":"/org/bluez/hci0"},"Alias":{"type":"s","data":"Studio Headset"},"Paired":{"type":"b","data":true},"Connected":{"type":"b","data":true},"Trusted":{"type":"b","data":true},"Icon":{"type":"s","data":"audio-headphones"},"RSSI":{"type":"n","data":-48}},"org.bluez.Battery1":{"Percentage":{"type":"y","data":73}}},"/org/bluez/hci0/dev_AA_BB_CC_DD_EE_02":{"org.bluez.Device1":{"Adapter":{"type":"o","data":"/org/bluez/hci0"},"Alias":{"type":"s","data":"Nearby Keyboard"},"Paired":{"type":"b","data":false},"Connected":{"type":"b","data":false},"Trusted":{"type":"b","data":false},"Icon":{"type":"s","data":"input-keyboard"},"RSSI":{"type":"n","data":-64}}}}]}
JSON
exit 0
fi

case "$*" in
  "--system set-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered b true"|\
  "--system set-property org.bluez /org/bluez/hci0 org.bluez.Adapter1 Powered b false"|\
  "--system call org.bluez /org/bluez/hci0 org.bluez.Adapter1 StartDiscovery"|\
  "--system call org.bluez /org/bluez/hci0 org.bluez.Adapter1 StopDiscovery"|\
  "--system call org.bluez /org/bluez/hci0/dev_AA_BB_CC_DD_EE_01 org.bluez.Device1 Connect"|\
  "--system call org.bluez /org/bluez/hci0/dev_AA_BB_CC_DD_EE_01 org.bluez.Device1 Disconnect"|\
  "--system call org.bluez /org/bluez/hci0/dev_AA_BB_CC_DD_EE_02 org.bluez.Device1 Pair"|\
  "--system call org.bluez /org/bluez/hci0 org.bluez.Adapter1 RemoveDevice o /org/bluez/hci0/dev_AA_BB_CC_DD_EE_01")
    exit 0
    ;;
  *)
    echo "unexpected fake busctl invocation: $*" >&2
    exit 64
    ;;
esac
EOF
chmod +x "$TMP/bin/busctl"
export FAKE_BUSCTL_LOG="$TMP/busctl.log"
: >"$FAKE_BUSCTL_LOG"
PATH="$TMP/bin:$PATH" python "$BT_BACKEND" snapshot >"$TMP/bluetooth-snapshot.json"
python - "$TMP/bluetooth-snapshot.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data["available"] is True
assert data["enabled"] is True
assert data["discovering"] is True
assert data["adapterPath"] == "/org/bluez/hci0"
assert len(data["paired"]) == 1
assert data["paired"][0]["name"] == "Studio Headset"
assert data["paired"][0]["connected"] is True
assert data["paired"][0]["battery"] == 73
assert data["paired"][0]["quality"] == "Excellent"
assert data["paired"][0]["type"] == "Headphones"
assert len(data["availableDevices"]) == 1
assert data["availableDevices"][0]["name"] == "Nearby Keyboard"
assert data["availableDevices"][0]["type"] == "Keyboard"
PY

echo "PASS"

echo "=== BlueZ actions use object paths, not device names ==="
PATH="$TMP/bin:$PATH" python "$BT_BACKEND" action toggle /org/bluez/hci0 on >"$TMP/bt-toggle.json"
PATH="$TMP/bin:$PATH" python "$BT_BACKEND" action scan-start /org/bluez/hci0 >"$TMP/bt-scan.json"
PATH="$TMP/bin:$PATH" python "$BT_BACKEND" action pair /org/bluez/hci0/dev_AA_BB_CC_DD_EE_02 >"$TMP/bt-pair.json"
PATH="$TMP/bin:$PATH" python "$BT_BACKEND" action forget /org/bluez/hci0 /org/bluez/hci0/dev_AA_BB_CC_DD_EE_01 >"$TMP/bt-forget.json"
python - "$TMP/bt-toggle.json" "$TMP/bt-scan.json" "$TMP/bt-pair.json" "$TMP/bt-forget.json" <<'PY'
import json, sys
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as handle:
        assert json.load(handle)["ok"] is True
PY
if grep -Fq 'Studio Headset' "$FAKE_BUSCTL_LOG"; then
    fail "Bluetooth device name leaked into busctl argv"
fi
echo "PASS"

echo "Maho Link contracts passed."
