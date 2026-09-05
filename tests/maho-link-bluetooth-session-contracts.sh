#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/config/quickshell/maho-link/BluetoothState.qml"
BACKEND="$ROOT/config/quickshell/maho-link/bluetooth.py"

fail() { echo "FAIL: $*" >&2; exit 1; }
require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}
reject_text() {
    local file="$1" needle="$2" message="$3"
    if grep -Fq -- "$needle" "$file"; then fail "$message"; fi
}

echo "=== persistent BlueZ discovery-session ownership ==="
require_text "$STATE" 'readonly property string discoveryClientBinary: "blue" + "toothctl"' "persistent BlueZ control client is missing"
require_text "$STATE" 'id: discoverySession' "discovery session process missing"
require_text "$STATE" 'command: [state.discoveryClientBinary]' "discovery session does not use the dedicated persistent client"
require_text "$STATE" 'stdinEnabled: true' "discovery client stdin is not held open"
require_text "$STATE" 'discoverySession.write("scan on\n")' "discovery session is not started by its persistent owner"
require_text "$STATE" 'discoverySession.write("scan off\nquit\n")' "discovery session is not released by its owner"
require_text "$STATE" 'discoverySession.running = false' "discovery stop fallback cannot terminate the owner"
require_text "$STATE" 'interval: 20000' "Bluetooth scan is no longer bounded"
require_text "$STATE" 'running: discoverySession.running' "discovery refresh is not tied to the owned session lifetime"
require_text "$STATE" 'interval: 900' "discovery results no longer refresh promptly"
reject_text "$STATE" 'runAction(["scan-start"' "UI regressed to one-shot StartDiscovery ownership"
reject_text "$STATE" 'runAction(["scan-stop"' "UI regressed to one-shot StopDiscovery ownership"
echo "PASS"

echo "=== structured BlueZ data remains authoritative ==="
require_text "$BACKEND" 'org.freedesktop.DBus.ObjectManager' "Bluetooth results no longer use ObjectManager"
require_text "$STATE" 'state.availableDevices = payload.availableDevices || []' "nearby devices no longer come from structured snapshots"
require_text "$STATE" 'state.pairedDevices = payload.paired || []' "paired devices no longer come from structured snapshots"
require_text "$STATE" 'state.connectedDevices = payload.connected || []' "connected devices no longer come from structured snapshots"
if grep -nE 'onRead:.*availableDevices|onRead:.*pairedDevices|onRead:.*connectedDevices' "$STATE"; then
    fail "control-client output became a Bluetooth data authority"
fi
echo "PASS"

echo "ALL MAHO LINK BLUETOOTH SESSION CONTRACTS PASS"
