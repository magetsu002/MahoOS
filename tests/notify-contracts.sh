#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
NOTIFY_DIR="$ROOT/config/quickshell/maho-notify"
RUNTIME="$ROOT/bin/maho-notify"
UNIT="$ROOT/systemd/user/maho-notify.service"

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

require_file() {
    [ -r "$NOTIFY_DIR/$1" ] || fail "missing Maho Notify component: $1"
}

require_text() {
    local file="$1" needle="$2" message="$3"
    grep -Fq -- "$needle" "$file" || fail "$message"
}

echo "=== packaged Maho Notify components ==="
for file in \
    shell.qml \
    NotificationService.qml \
    NotificationModel.qml \
    NotificationStack.qml \
    NotificationCard.qml \
    NotifyTheme.qml \
    HistoryModel.qml \
    state.py
do
    require_file "$file"
done
echo "PASS"

echo "=== native notification server contract ==="
require_text "$NOTIFY_DIR/NotificationService.qml" 'import Quickshell.Services.Notifications' "native notification service import missing"
require_text "$NOTIFY_DIR/NotificationService.qml" 'NotificationServer {' "NotificationServer missing"
require_text "$NOTIFY_DIR/NotificationService.qml" 'notification.tracked = true' "notifications are not retained"
require_text "$NOTIFY_DIR/NotificationService.qml" 'bodySupported: true' "body capability is not advertised"
require_text "$NOTIFY_DIR/NotificationService.qml" 'actionsSupported: true' "action capability is not advertised"
require_text "$NOTIFY_DIR/NotificationService.qml" 'bodyMarkupSupported: false' "unsupported markup capability advertised"
require_text "$NOTIFY_DIR/NotificationService.qml" 'bodyHyperlinksSupported: false' "unsupported hyperlink capability advertised"
require_text "$NOTIFY_DIR/NotificationService.qml" 'inlineReplySupported: false' "unsupported inline reply capability advertised"
require_text "$NOTIFY_DIR/NotificationService.qml" 'persistenceSupported: true' "implemented persistence capability is not advertised"
echo "PASS"

echo "=== private bounded history contract ==="
require_text "$NOTIFY_DIR/HistoryModel.qml" 'readonly property int maxEntries: 500' "history entry bound missing"
require_text "$NOTIFY_DIR/HistoryModel.qml" '7 * 24 * 60 * 60 * 1000' "seven-day history retention missing"
require_text "$NOTIFY_DIR/HistoryModel.qml" 'notification.transient' "transient notification handling missing"
require_text "$NOTIFY_DIR/HistoryModel.qml" 'delete copy.transient' "transient snapshots are not excluded from persistence"
require_text "$NOTIFY_DIR/HistoryModel.qml" 'replacementCount' "protocol replacement history handling missing"
require_text "$NOTIFY_DIR/HistoryModel.qml" 'notification.summaryChanged.connect' "replacement updates are not observed"
require_text "$NOTIFY_DIR/state.py" 'XDG_STATE_HOME' "history does not use user state storage"
require_text "$NOTIFY_DIR/state.py" 'MAX_ENTRIES = 500' "persistence entry bound missing"
require_text "$NOTIFY_DIR/state.py" 'MAX_AGE_SECONDS = 7 * 24 * 60 * 60' "persistence age bound missing"
require_text "$NOTIFY_DIR/state.py" 'os.fchmod(fd, 0o600)' "private state file mode missing"
require_text "$NOTIFY_DIR/state.py" 'os.chmod(directory, 0o700)' "private state directory mode missing"
require_text "$NOTIFY_DIR/state.py" 'os.replace(temporary, path)' "atomic persistence replacement missing"
echo "PASS"

echo "=== bounded popup contract ==="
require_text "$NOTIFY_DIR/NotificationModel.qml" 'readonly property int maxVisible: 3' "visible popup maximum is not three"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'queuedNotifications' "overflow queue missing"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'maximumLineCount: 3' "long notification bodies are not clamped"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'textFormat: Text.PlainText' "notification text can render unadvertised markup"
require_text "$NOTIFY_DIR/NotificationStack.qml" 'width: 324' "compact popup width contract missing"
require_text "$NOTIFY_DIR/shell.qml" 'overlay.width - width - 18' "top-right placement missing"
require_text "$NOTIFY_DIR/shell.qml" 'y: 18' "top safe margin missing"
require_text "$NOTIFY_DIR/shell.qml" 'exclusionMode: ExclusionMode.Ignore' "popup may reserve compositor space"
echo "PASS"

echo "=== lifecycle and interaction contract ==="
require_text "$NOTIFY_DIR/NotificationCard.qml" 'Math.round(notification.expireTimeout)' "application expiration hint is not consumed"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'notification.expire()' "timeout expiry path missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'notification.dismiss()' "user dismissal path missing"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'notification.actions[index].invoke()' "app action invocation path missing"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'Math.min(2, notification.actions.length)' "action row is not bounded"
echo "PASS"

echo "=== palette and independence contract ==="
require_text "$NOTIFY_DIR/NotifyTheme.qml" '/.cache/maho/theme/active.json' "Maho active palette is not used"
require_text "$NOTIFY_DIR/NotifyTheme.qml" 'watchChanges: true' "active palette changes are not watched"
if grep -RnsE 'maho-shell|EdgeBar|SideEdgeBar|ControlCenter|DockReservation' "$NOTIFY_DIR" --include='*.qml'; then
    fail "Maho Notify depends on frozen Maho Edge components"
fi
echo "PASS"

echo "=== privacy contract ==="
if grep -RnsE 'console\.(log|info|warn|error).*body|print\(.*body|echo.*notification.*body' "$NOTIFY_DIR" "$RUNTIME"; then
    fail "notification body logging found"
fi
if find "$ROOT/tests" -type f -iname '*notif*' ! -name 'notify-contracts.sh' -print | grep -q .; then
    fail "unexpected notification fixture found; use synthetic runtime messages only"
fi
echo "PASS"

echo "=== managed runtime contract ==="
[ -x "$RUNTIME" ] || fail "maho-notify runtime is not executable"
[ -r "$UNIT" ] || fail "maho-notify user service missing"
require_text "$RUNTIME" 'doctor)' "doctor command missing"
require_text "$RUNTIME" 'status --json' "machine-readable status missing"
require_text "$RUNTIME" 'logs [LINES]' "bounded logs command missing"
require_text "$RUNTIME" 'if [ "$lines" -lt 1 ] || [ "$lines" -gt 500 ]' "runtime log bound missing"
require_text "$RUNTIME" 'refusing to displace the current notification server' "existing notification owner is not protected"
require_text "$RUNTIME" 'pgrep -x quickshell' "runtime process matching is not executable-bounded"
require_text "$UNIT" 'maho-notify run' "user service does not use managed runtime"
require_text "$ROOT/bin/maho-setup" 'maho-notify' "setup packaging does not know Maho Notify"
bash -n "$RUNTIME"
echo "PASS"

echo "ALL MAHO NOTIFY CONTRACTS PASS"
