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

echo "=== shared buttons use one hover plane ==="
require_text "$BUTTON" 'id: hoverPlane' "shared Maho Link button has no single hover plane"
require_text "$BUTTON" 'Behavior on opacity' "shared button hover plane is not animated once"
reject_text "$BUTTON" 'Behavior on border.color' "shared button still animates a second hover rim"
reject_text "$BUTTON" 'hover.containsMouse ? 0.72 : 0.64' "primary button still drives fill directly from hover"
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

echo "ALL SINGLE-HOVER CONTRACTS PASS"
