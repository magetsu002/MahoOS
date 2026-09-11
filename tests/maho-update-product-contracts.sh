#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SHELL_DIR="$ROOT/config/quickshell/maho-shell"
POWER_DIR="$ROOT/config/quickshell/maho-power"
NOTIFY_DIR="$ROOT/config/quickshell/maho-notify"

fail() { echo "FAIL: $*" >&2; exit 1; }
require() { grep -Fq -- "$2" "$1" || fail "$3"; }
reject() { ! grep -Fq -- "$2" "$1" || fail "$3"; }

bash -n "$ROOT/bin/maho-update"
python -m py_compile "$ROOT/lib/maho_update_cli.py"
[ -x "$ROOT/bin/maho-update" ] || fail "maho-update product CLI is not executable"
require "$ROOT/bin/maho-setup" 'maho-power maho-update maho-clipboard' "setup does not ship Maho Update"
echo "PASS Maho Update is shipped through immutable runtime setup"

for state in "$SHELL_DIR/MahoUpdateState.qml" "$POWER_DIR/MahoUpdateState.qml"; do
    require "$state" '/.local/bin/maho-update", "status", "--json"' "product state does not consume shared authority CLI"
    reject "$state" 'property bool updated' "UI invented a vague local updated boolean"
done
require "$SHELL_DIR/shell.qml" 'MahoUpdateState { id: updateState }' "Maho Edge does not instantiate shared update projection"
require "$SHELL_DIR/ControlCenter.qml" 'System maintenance · ' "Settings/update surface lacks maintenance status"
require "$SHELL_DIR/ControlCenter.qml" 'lastMaintenance' "Settings/update surface lacks last maintenance"
require "$SHELL_DIR/ControlCenter.qml" 'historyCount' "Settings/update surface lacks receipt history"
require "$SHELL_DIR/ControlCenter.qml" 'blockers.join' "Settings/update surface lacks actionable blockers"
reject "$SHELL_DIR/ControlCenter.qml" 'package count' "Settings promotes package-count nagging"
echo "PASS Settings/update visibility consumes authoritative status and receipts"

require "$SHELL_DIR/EdgeBar.qml" 'activationPending || edge.updateState.attentionRequired' "horizontal Edge lacks passive update state"
require "$SHELL_DIR/SideEdgeBar.qml" 'activationPending || edge.updateState.attentionRequired' "side Edge lacks passive update state"
reject "$SHELL_DIR/EdgeBar.qml" 'historyCount' "horizontal Edge became an update dashboard"
reject "$SHELL_DIR/SideEdgeBar.qml" 'historyCount' "side Edge became an update dashboard"
echo "PASS Maho Edge exposes passive activation/attention state only"

require "$NOTIFY_DIR/shell.qml" 'UpdateAttention { }' "Maho Notify does not consume update attention state"
require "$NOTIFY_DIR/UpdateAttention.qml" 'data.notification_policy !== "one-meaningful-attention"' "routine updates may create popups"
require "$NOTIFY_DIR/UpdateAttention.qml" 'transaction === deliveryState.transactionId' "update attention is not deduplicated"
require "$NOTIFY_DIR/UpdateAttention.qml" 'Quickshell.statePath("update-attention.json")' "attention deduplication is not durable"
require "$NOTIFY_DIR/UpdateAttention.qml" '"--urgency=normal"' "update attention bypasses existing DND behavior"
echo "PASS Maho Notify is silent for routine success and emits one DND-respecting attention"

cmp -s "$SHELL_DIR/MahoPowerView.qml" "$POWER_DIR/MahoPowerView.qml" || fail "Power views no longer share product authority"
require "$POWER_DIR/shell.qml" 'MahoUpdateState { id: updateState }' "standalone Power does not consume update state"
require "$SHELL_DIR/MahoPowerView.qml" 'root.updateState.activationPending || root.updateState.attentionRequired' "Power does not surface meaningful update state"
require "$ROOT/bin/maho-power" 'restart)' "ordinary Restart was removed"
require "$ROOT/bin/maho-power" 'exec systemctl reboot' "ordinary Restart no longer passes through immediately"
require "$ROOT/bin/maho-power" 'shutdown)' "ordinary Shut Down was removed"
require "$ROOT/bin/maho-power" 'exec systemctl poweroff' "ordinary Shut Down no longer passes through immediately"
reject "$ROOT/bin/maho-power" 'maho-update' "ordinary power actions were coupled to update execution"
echo "PASS Power preserves plain Restart and Shut Down while consuming meaningful status"

if rg -n 'pacman|reboot|shutdown|poweroff|efibootmgr|BootOrder|BootNext' "$ROOT/bin/maho-update" "$ROOT/lib/maho_update_cli.py"; then
    fail "read-only product CLI contains host mutation authority"
fi
echo "ALL MAHO UPDATE PRODUCT INTEGRATION CONTRACTS PASS"
