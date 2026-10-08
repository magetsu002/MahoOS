#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/config/quickshell/maho-link/BluetoothState.qml"
BT_MAIN="$ROOT/config/quickshell/maho-link/BluetoothMain.qml"
WIFI_MAIN="$ROOT/config/quickshell/maho-link/MahoLinkMain.qml"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}
reject_text() {
    local file="$1" needle="$2" message="$3"
    if grep -Fq -- "$needle" "$file"; then fail "$message"; fi
}

echo "=== Bluetooth discovery does not flicker the power control ==="
require_text "$STATE" 'actionProcess.running || cancelProcess.running || pairingProcess.running' "interactive Bluetooth busy state no longer includes pairing without snapshot churn"
reject_text "$STATE" 'readonly property bool busy: snapshotProcess.running' "Bluetooth snapshot refresh still drives interactive busy state"
echo "PASS"

echo "=== connectivity scan indicators use centered status lanes ==="
require_text "$BT_MAIN" 'id: discoveryStatusLane' "Bluetooth discovery status lane missing"
require_text "$BT_MAIN" 'height: 18' "Bluetooth discovery status lane lost fixed centering geometry"
require_text "$BT_MAIN" 'anchors.centerIn: parent' "Bluetooth discovery dot is not centered in its lane"
require_text "$WIFI_MAIN" 'id: scanStatusLane' "Wi-Fi scan status lane missing"
require_text "$WIFI_MAIN" 'height: 18' "Wi-Fi scan status lane lost fixed centering geometry"
require_text "$WIFI_MAIN" 'anchors.centerIn: parent' "Wi-Fi scan dot is not centered in its lane"
echo "PASS"

echo "ALL CONNECTIVITY INDICATOR POLISH CONTRACTS PASS"
