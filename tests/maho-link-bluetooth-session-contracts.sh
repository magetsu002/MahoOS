#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
STATE="$ROOT/config/quickshell/maho-link/BluetoothState.qml"
BACKEND="$ROOT/config/quickshell/maho-link/bluetooth.py"
SESSION_POLICY="$ROOT/config/quickshell/maho-shell/BluetoothAutoConnect.qml"
SHELL="$ROOT/config/quickshell/maho-shell/shell.qml"
LAUNCHER="$ROOT/bin/maho-link"

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

echo "=== bounded trusted-audio auto-connect policy ==="
require_text "$BACKEND" 'row["paired"] and row["trusted"] and not row["connected"]' "auto-connect does not require paired and trusted BlueZ truth"
require_text "$BACKEND" 'row["kind"] in ("headphones", "speaker")' "auto-connect is not limited to audio devices"
require_text "$BACKEND" '"bonded": bonded_flag' "BlueZ Bonded truth is not exposed independently"
require_text "$BACKEND" 'elif enabled and row["discovered"]' "stale unknown objects can appear as available Pair targets"
require_text "$BACKEND" 'merge_device_rows(device_rows)' "device identity is not deduplicated before presentation"
require_text "$BACKEND" 'AUTOCONNECT_BACKOFF_SECONDS = (5, 15, 45, 120)' "auto-connect retry backoff is missing or unbounded"
require_text "$BACKEND" 'state["suppressed"]' "intentional disconnect suppression is not backend-owned"
require_text "$STATE" '["python", backendPath(), "auto-connect"]' "Bluetooth state never invokes the backend policy"
require_text "$STATE" 'state.autoConnectEligible = payload.autoConnectEligible || []' "QML does not consume authoritative eligibility"
require_text "$BACKEND" 'connection_operation(blocking=False)' "concurrent Maho surfaces can race auto-connect"
require_text "$BACKEND" 'connection_operation(blocking=True)' "manual Bluetooth actions can race auto-connect"
python3 "$ROOT/tests/maho-link-bluetooth-policy-tests.py"
echo "PASS"

echo "=== session-lifetime policy ownership ==="
require_text "$SHELL" 'BluetoothAutoConnect { }' "persistent Maho Shell does not own auto-connect lifecycle"
require_text "$SESSION_POLICY" '"auto-connect-policy"' "session owner does not invoke the bounded backend policy"
require_text "$SESSION_POLICY" 'command: ["busctl", "--system", "monitor", "org.bluez"]' "session owner does not observe BlueZ transitions"
require_text "$SESSION_POLICY" 'interval: 12000' "session owner has no bounded monitor fallback"
require_text "$LAUNCHER" 'auto-connect-policy)' "installed Maho Link command does not expose the internal policy action"
require_text "$LAUNCHER" 'bluetooth.py" auto-connect' "internal policy action does not route to the release backend"
reject_text "$SESSION_POLICY" 'Pair' "session owner may not auto-pair devices"
reject_text "$SESSION_POLICY" 'Trusted' "session owner may not mutate BlueZ trust"
echo "PASS"

echo "ALL MAHO LINK BLUETOOTH SESSION CONTRACTS PASS"
