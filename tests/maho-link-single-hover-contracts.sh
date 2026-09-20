#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LINK="$ROOT/config/quickshell/maho-link"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject_text() { if grep -Fq -- "$2" "$1"; then fail "$3"; fi; }

BUTTON="$LINK/MahoLinkButton.qml"
BT_ROW="$LINK/BluetoothDeviceRow.qml"
WIFI_ROW="$LINK/MahoLinkNetworkRow.qml"
WIFI_MAIN="$LINK/MahoLinkMain.qml"
BT_MAIN="$LINK/BluetoothMain.qml"
WIFI_DETAILS="$LINK/MahoLinkDetails.qml"
BT_DETAILS="$LINK/BluetoothDetails.qml"

echo "=== shared buttons use one hover plane ==="
require_text "$BUTTON" 'id: hoverPlane' "shared Maho Link button has no single hover plane"
require_text "$BUTTON" 'Behavior on opacity' "shared button hover plane is not animated once"
reject_text "$BUTTON" 'Behavior on border.color' "shared button still animates a second hover rim"
echo PASS

echo "=== Bluetooth rows do not stack hover channels ==="
require_text "$BT_ROW" 'id: rowHoverPlane' "Bluetooth row has no single hover plane"
require_text "$BT_ROW" 'id: actionHoverPlane' "Bluetooth action has no single hover plane"
reject_text "$BT_ROW" 'scale: rowHover.containsMouse ?' "Bluetooth row still zooms its icon on hover"
reject_text "$BT_ROW" 'Behavior on border.color' "Bluetooth Pair still animates a separate hover rim"
echo PASS

echo "=== Wi-Fi rows do not stack hover channels ==="
require_text "$WIFI_ROW" 'id: rowHoverPlane' "Wi-Fi row has no single hover plane"
reject_text "$WIFI_ROW" 'scale: hover.containsMouse ?' "Wi-Fi row still zooms its icon on hover"
reject_text "$WIFI_ROW" 'glyphColor: hover.containsMouse' "Wi-Fi row still runs a second icon hover state"
reject_text "$WIFI_ROW" 'color: hover.containsMouse' "Wi-Fi row still runs a second chevron hover state"
echo PASS

echo "=== Wi-Fi main/detail surfaces use one hover plane ==="
require_text "$WIFI_MAIN" 'id: currentHoverPlane' "connected Wi-Fi card has stacked hover styling"
require_text "$WIFI_MAIN" 'id: otherHoverPlane' "Other Network row has stacked hover styling"
reject_text "$WIFI_MAIN" 'Behavior on border.color' "Wi-Fi main still animates a second hover rim"
require_text "$WIFI_DETAILS" 'id: disconnectHoverPlane' "Wi-Fi Disconnect action has stacked hover styling"
reject_text "$WIFI_DETAILS" 'Behavior on border.color' "Wi-Fi detail action still animates a second hover rim"
echo PASS

echo "=== Bluetooth main/detail surfaces use one hover plane ==="
require_text "$BT_MAIN" 'id: heroHoverPlane' "Bluetooth connected hero has stacked hover styling"
require_text "$BT_MAIN" 'id: pairHoverPlane' "Pair New Device card has stacked hover styling"
reject_text "$BT_MAIN" 'Behavior on border.color' "Bluetooth main still animates a second hover rim"
require_text "$BT_DETAILS" 'id: connectHoverPlane' "Bluetooth Connect action has stacked hover styling"
require_text "$BT_DETAILS" 'id: forgetHoverPlane' "Bluetooth Forget action has stacked hover styling"
[ "$(grep -Fc 'visible: Boolean(device && device.connected)' "$BT_DETAILS")" -eq 2 ] || fail "Bluetooth detail visibility is not strict-boolean safe"
reject_text "$BT_DETAILS" 'visible: device && device.connected' "Bluetooth detail visibility can still assign undefined to bool"
echo PASS

echo "ALL SINGLE-HOVER CONTRACTS PASS"
