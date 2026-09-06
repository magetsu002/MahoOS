#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LINK="$ROOT/config/quickshell/maho-link"
SHELL="$LINK/shell.qml"
STATE="$LINK/MahoLinkState.qml"
BT_STATE="$LINK/BluetoothState.qml"
BACKEND="$LINK/wifi.py"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}

reject_text() {
    local file="$1" needle="$2" message="$3"
    if grep -Fq -- "$needle" "$file"; then
        fail "$message"
    fi
}

echo "=== persistent draggable Maho Link ==="
require_text "$SHELL" 'readonly property string linkPlacementPath: stateBase + "/maho/link-position.json"' "Link does not use one atomic product placement file"
require_text "$SHELL" '"python3", positionHelperPath, "load"' "mode-keyed Link placement file is not loaded by the runtime authority"
reject_text "$SHELL" 'Quickshell.statePath("link-position.json")' "placement is still scoped to a Quickshell runtime instead of Maho Link"
require_text "$SHELL" 'function persistPlacement()' "drag completion does not persist placement"
require_text "$SHELL" 'drag.target: linkSurface' "shared Wi-Fi/Bluetooth surface is not the drag target"
require_text "$SHELL" 'width: Math.max(80, linkSurface.width - 184)' "drag handle is not constrained to the safe title strip"
require_text "$SHELL" 'drag.minimumX: root.surfaceMarginX' "dragging is not clamped horizontally"
require_text "$SHELL" 'drag.maximumY: root.maximumSurfaceY()' "dragging is not clamped vertically"
require_text "$SHELL" 'onHeightChanged:' "dynamic surface-height placement is not re-clamped"
require_text "$SHELL" 'if (placementValid)' "persisted placement does not override first-run Edge placement"
require_text "$SHELL" 'surfaceX(overlay.width, linkSurface.width, surfaceMarginX)' "first-run placement no longer respects Maho Edge"
echo "PASS"

echo "=== two-phase Wi-Fi UI contract ==="
require_text "$STATE" 'property bool statusReady: false' "fast authoritative status readiness is missing"
require_text "$STATE" 'property bool networksReady: false' "network discovery readiness is not independent"
require_text "$STATE" '["python", backendPath(), "status"]' "QML does not request fast NetworkManager status"
require_text "$STATE" '["python", backendPath(), "networks"]' "QML does not request cached network discovery independently"
require_text "$STATE" 'readonly property bool busy: actionProcess.running || scanning' "background startup discovery still presents itself as an active scan"
require_text "$SHELL" '!wifi.statusReady' "Wi-Fi surface can paint placeholder state before authoritative status"
require_text "$SHELL" 'wifi.refresh()' "Wi-Fi status/discovery does not start when opened"
require_text "$BACKEND" 'scan_networks(enabled, rescan="no")' "startup network discovery is still allowed to trigger a rescan"
require_text "$BACKEND" 'if sys.argv[1] == "status"' "fast status backend mode missing"
require_text "$BACKEND" 'if sys.argv[1] == "networks"' "cached networks backend mode missing"
echo "PASS"

echo "=== responsive BlueZ discovery contract ==="
require_text "$BT_STATE" 'id: discoverySession' "Bluetooth discovery has no persistent session owner"
require_text "$BT_STATE" 'stdinEnabled: true' "Bluetooth discovery owner does not keep its D-Bus client alive"
require_text "$BT_STATE" 'discoverySession.write("scan on\n")' "Bluetooth discovery owner never starts scanning"
require_text "$BT_STATE" 'discoverySession.write("scan off\nquit\n")' "Bluetooth discovery owner never releases its scan"
require_text "$BT_STATE" 'id: discoveryRefresh' "Bluetooth discovery has no responsive snapshot cadence"
require_text "$BT_STATE" 'interval: 900' "Bluetooth discovery refresh cadence drifted"
require_text "$BT_STATE" 'running: discoverySession.running' "Bluetooth discovery refresh is not bounded to the owned session"
require_text "$BT_STATE" 'state.discovering = Boolean(payload.discovering) || discoverySession.running' "Bluetooth UI can fall out of discovery state before BlueZ catches up"
require_text "$BT_STATE" 'interval: 20000' "Bluetooth discovery is not safely bounded"
echo "PASS"

echo "=== deterministic fast NetworkManager status ==="
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
cat >"$TMP/bin/nmcli" <<'EOF_NMCLI'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_NMCLI_LOG:?}"
case "$*" in
  "-t -f WIFI general")
    echo "enabled"
    ;;
  "-t -e yes -f DEVICE,TYPE,STATE device status")
    echo "wlan0:wifi:connected"
    ;;
  "-t -e yes -f NAME,UUID,TYPE,DEVICE connection show --active")
    echo "Home Profile:11111111-2222-3333-4444-555555555555:802-11-wireless:wlan0"
    ;;
  "-t -g 802-11-wireless.ssid connection show uuid 11111111-2222-3333-4444-555555555555")
    echo "Ashraf4G"
    ;;
  "-t -e yes -f IP4.ADDRESS,IP4.GATEWAY device show wlan0")
    echo "IP4.ADDRESS[1]:192.168.1.50/24"
    echo "IP4.GATEWAY:192.168.1.1"
    ;;
  "-t -e yes -f IN-USE,SSID,SIGNAL,SECURITY,FREQ device wifi list --rescan no")
    echo "*:Ashraf4G:91:WPA2:5180"
    echo ":Guest:61:WPA2:2412"
    ;;
  *)
    echo "unexpected fake nmcli invocation: $*" >&2
    exit 64
    ;;
esac
EOF_NMCLI
chmod +x "$TMP/bin/nmcli"
export FAKE_NMCLI_LOG="$TMP/nmcli.log"
: >"$FAKE_NMCLI_LOG"

PATH="$TMP/bin:$PATH" python "$BACKEND" status >"$TMP/status.json"
python - "$TMP/status.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data["available"] is True
assert data["enabled"] is True
assert data["device"] == "wlan0"
assert data["current"]["ssid"] == "Ashraf4G"
assert data["current"]["uuid"] == "11111111-2222-3333-4444-555555555555"
assert data["current"]["state"] == "Connected"
assert data["current"]["signal"] == -1
assert data["current"]["ipv4"] == "192.168.1.50/24"
PY
if grep -Fq 'device wifi list' "$FAKE_NMCLI_LOG"; then
    fail "fast status path waited on Wi-Fi discovery"
fi

: >"$FAKE_NMCLI_LOG"
PATH="$TMP/bin:$PATH" python "$BACKEND" networks >"$TMP/networks.json"
python - "$TMP/networks.json" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
assert data["current"]["ssid"] == "Ashraf4G"
assert data["current"]["signal"] == 91
assert [row["ssid"] for row in data["networks"]] == ["Guest"]
PY
grep -Fq 'device wifi list --rescan no' "$FAKE_NMCLI_LOG" || fail "startup discovery did not use cached NetworkManager data"
if grep -Fq 'device wifi rescan' "$FAKE_NMCLI_LOG"; then
    fail "startup discovery explicitly triggered a scan"
fi
echo "PASS"

echo "ALL DRAG/STARTUP CONTRACTS PASS"
