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
    AppIdentityResolver.qml \
    AppIcon.qml \
    NotificationModel.qml \
    NotificationStack.qml \
    NotificationCard.qml \
    NotifyTheme.qml \
    HistoryModel.qml \
    NotificationCenter.qml \
    HistoryRow.qml \
    state.py
do
    require_file "$file"
done
echo "PASS"

echo "=== application identity and icon resolution contract ==="
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'DesktopEntries.applications.values' "resolver does not use the native desktop-entry model"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'function rebuildIndex()' "desktop entries are not centrally indexed"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'function entryForDesktopId' "desktop-entry identity matching missing"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'function entryForAppName' "exact app-name identity matching missing"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'return matches.length === 1 ? matches[0] : null' "ambiguous identities do not fail safely"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'Quickshell.hasThemeIcon(icon)' "explicit theme icons are not validated"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" '"explicit-icon"' "explicit icon priority missing"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" '"desktop-entry"' "desktop-entry icon priority missing"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" '"app-name"' "app-name icon priority missing"
require_text "$NOTIFY_DIR/AppIdentityResolver.qml" 'isNetworkSource(icon)' "network icon sources are not rejected"
require_text "$NOTIFY_DIR/AppIcon.qml" 'status === Image.Error' "invalid local icons do not fall through safely"
require_text "$NOTIFY_DIR/AppIcon.qml" 'fillMode: Image.PreserveAspectFit' "application icons may be stretched"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'iconSize: 26' "accepted popup app-icon target changed"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'identityResolver: card.identityResolver' "popup bypasses the central resolver"
require_text "$NOTIFY_DIR/HistoryRow.qml" 'identityResolver: row.identityResolver' "history bypasses the central resolver"
require_text "$NOTIFY_DIR/HistoryModel.qml" 'identityResolver.stableDesktopEntry(notification)' "history does not persist stable desktop identity"
require_text "$NOTIFY_DIR/HistoryModel.qml" 'identityResolver.stableIconName(notification.appIcon)' "history icon persistence is not bounded to theme identities"
require_text "$NOTIFY_DIR/state.py" '"desktopEntry": 192' "persisted desktop identity is not bounded"
if grep -nE 'source:.*notification\.image|\?.*notification\.image' "$NOTIFY_DIR/NotificationCard.qml"; then
    fail "notification content image is still used as application identity"
fi
if grep -RnsE 'https?://|ftp://' "$NOTIFY_DIR/AppIcon.qml"; then
    fail "app icon renderer contains a network source"
fi
if grep -RnsE 'Process|execDetached|find |grep |\.desktop files' "$NOTIFY_DIR/AppIdentityResolver.qml"; then
    fail "identity resolver performs per-notification process or filesystem scanning"
fi
echo "PASS"

echo "=== notification center contract ==="
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'width: 432' "notification center width is not premium-bounded"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'Math.min(704' "notification center height is not premium-bounded"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'ListView {' "history center is not virtualized"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'reuseItems: true' "history rows are not reusable"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'model: historyModel.groupedEntries' "center does not consume grouped history"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'historyModel.dndEnabled' "center DND control missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'String(historyModel.unreadCount) + " unread"' "center unread badge missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'historyModel.markAllRead()' "center read path missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'historyModel.clearHistory()' "center clear-history path missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'section.property: "section"' "minimal history time sections missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'interval: 60000' "relative-time refresh is missing or unbounded"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'running: center.shown' "relative-time refresh runs while center is closed"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'text: "All clear"' "premium empty state missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'duration: center.shown ? 210 : 155' "restrained center presentation motion missing"
require_text "$NOTIFY_DIR/NotificationCenter.qml" 'gradient: Gradient {' "adaptive center material depth missing"
require_text "$NOTIFY_DIR/HistoryRow.qml" 'readonly property bool unread:' "read/unread row distinction missing"
require_text "$NOTIFY_DIR/HistoryRow.qml" 'visible: row.unread' "unread accent rail missing"
require_text "$NOTIFY_DIR/HistoryRow.qml" 'String(entry.groupCount) + " grouped"' "grouped-entry count badge missing"
require_text "$NOTIFY_DIR/HistoryRow.qml" 'maximumLineCount: row.expanded ? 8 : 2' "expanded history body is not bounded"
if grep -Fq '.invoke()' "$NOTIFY_DIR/HistoryRow.qml"; then
    fail "historical rows expose stale live actions"
fi
require_text "$NOTIFY_DIR/shell.qml" 'exclusionMode: ExclusionMode.Ignore' "center may reserve compositor space"
require_text "$NOTIFY_DIR/shell.qml" 'visible: root.centerPresented' "center close animation does not remain independently presented"
require_text "$RUNTIME" 'open_center' "center runtime command missing"
echo "PASS"

echo "=== privacy-safe status bridge contract ==="
require_text "$NOTIFY_DIR/HistoryModel.qml" '"op": "publish_status"' "reactive metadata export missing"
require_text "$NOTIFY_DIR/HistoryModel.qml" '"unread_count": unreadCount' "metadata does not update from unread state"
require_text "$NOTIFY_DIR/HistoryModel.qml" '"dnd": dndEnabled' "metadata does not update from DND state"
require_text "$NOTIFY_DIR/state.py" 'return runtime_dir() / "notify-status.json"' "metadata is not stored in user runtime space"
require_text "$NOTIFY_DIR/state.py" '"version": STATUS_VERSION' "metadata schema version missing"
require_text "$NOTIFY_DIR/state.py" '"active": active_value' "metadata active state missing"
require_text "$NOTIFY_DIR/state.py" 'set(persisted_status) == {"version", "unread_count", "dnd", "active", "pid"}' "metadata schema allowlist self-test missing"
require_text "$NOTIFY_DIR/state.py" '"pid": os.getppid() if active_value else 0' "metadata does not identify its live Quickshell owner"
require_text "$NOTIFY_DIR/state.py" 'publish_status(last_status, active=False)' "metadata does not become inactive on clean shutdown"
if grep -nE 'normalize_status|publish_status' "$NOTIFY_DIR/state.py" | grep -E 'body|summary|appName|title'; then
    fail "notification content field found in metadata implementation"
fi
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
python "$NOTIFY_DIR/state.py" self-test | grep -Fq 'PASS state self-test' || fail "history retention/recovery self-test failed"
echo "PASS"

echo "=== bounded popup contract ==="
require_text "$NOTIFY_DIR/NotificationModel.qml" 'readonly property int maxVisible: 3' "visible popup maximum is not three"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'readonly property int maxQueued: 100' "popup queue bound missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'queuedNotifications' "overflow queue missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'groupingWindowMs: 6000' "same-app popup grouping missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'groupCount' "popup group count missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'NotificationUrgency.Critical' "critical popup policy missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'dndEnabled && !critical' "DND suppression path missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'notification.expire()' "suppressed popup does not release live notification"
require_text "$NOTIFY_DIR/shell.qml" 'historyModel.record(notification)' "history path does not precede popup policy"
require_text "$NOTIFY_DIR/shell.qml" 'notificationModel.enqueue(notification, historyModel.dndEnabled)' "DND does not control popup path"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'maximumLineCount: 3' "long notification bodies are not clamped"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'textFormat: Text.PlainText' "notification text can render unadvertised markup"
require_text "$NOTIFY_DIR/NotificationStack.qml" 'width: 324' "compact popup width contract missing"
require_text "$NOTIFY_DIR/shell.qml" '/quickshell/by-shell/maho-shell/dock.json' "Maho Notify does not observe Edge placement"
require_text "$NOTIFY_DIR/shell.qml" 'readonly property real dockPosition:' "Maho Notify ignores along-edge position"
require_text "$NOTIFY_DIR/shell.qml" 'dockPosition > 0.5' "Maho Notify cannot detect a top/bottom Edge on the right half"
require_text "$NOTIFY_DIR/shell.qml" 'if (dockOccupiesRightSide)' "Maho Notify does not move opposite the Edge location"
require_text "$NOTIFY_DIR/shell.qml" 'x: root.surfaceX(overlay.width, width, 18)' "popup placement is not Edge-aware"
require_text "$NOTIFY_DIR/shell.qml" 'x: root.surfaceX(centerOverlay.width, width, 18)' "notification center placement is not Edge-aware"
require_text "$NOTIFY_DIR/shell.qml" 'y: 18' "top safe margin missing"
require_text "$NOTIFY_DIR/shell.qml" 'exclusionMode: ExclusionMode.Ignore' "popup may reserve compositor space"
echo "PASS"

echo "=== lifecycle and interaction contract ==="
require_text "$NOTIFY_DIR/NotificationCard.qml" 'Math.round(notification.expireTimeout)' "application expiration hint is not consumed"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'card.expireRequested()' "timeout expiry path missing"
require_text "$NOTIFY_DIR/NotificationModel.qml" 'group.notification.dismiss()' "user dismissal path missing"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'notification.actions[index].invoke()' "app action invocation path missing"
require_text "$NOTIFY_DIR/NotificationCard.qml" 'Math.min(2, notification.actions.length)' "action row is not bounded"
echo "PASS"

echo "=== palette and independence contract ==="
require_text "$NOTIFY_DIR/NotifyTheme.qml" '/.cache/maho/theme/active.json' "Maho active palette is not used"
require_text "$NOTIFY_DIR/NotifyTheme.qml" 'watchChanges: true' "active palette changes are not watched"
if grep -RnsE 'EdgeBar|SideEdgeBar|ControlCenter|DockReservation' "$NOTIFY_DIR" --include='*.qml'; then
    fail "Maho Notify imports or owns frozen Maho Edge components"
fi
MAHO_SHELL_REFS="$(grep -RhsF 'maho-shell' "$NOTIFY_DIR" --include='*.qml' | wc -l | tr -d ' ')"
[ "$MAHO_SHELL_REFS" -eq 1 ] || fail "Maho Notify has a broader Maho Shell dependency than dock placement"
echo "PASS"

echo "=== privacy contract ==="
if grep -RnsE 'console\.(log|info|warn|error).*body|print\(.*body|echo.*notification.*body' "$NOTIFY_DIR" "$RUNTIME"; then
    fail "notification body logging found"
fi
if grep -RnsE 'console\.(log|info|warn|error)' "$NOTIFY_DIR" --include='*.qml'; then
    fail "notification QML console logging can expose private content"
fi
if grep -RnsE 'console\.(log|info|warn|error).*summary|console\.(log|info|warn|error).*hints' "$NOTIFY_DIR" --include='*.qml'; then
    fail "notification summary or hint logging found"
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
require_text "$RUNTIME" 'manage_dnd' "DND runtime commands missing"
require_text "$RUNTIME" 'clear_history' "history clear runtime command missing"
require_text "$RUNTIME" '"history_count"' "status does not expose retained history count"
require_text "$RUNTIME" '"unread_count"' "status does not expose unread count"
require_text "$RUNTIME" '"dnd"' "status does not expose DND state"
require_text "$RUNTIME" 'logs [LINES]' "bounded logs command missing"
require_text "$RUNTIME" 'if [ "$lines" -lt 1 ] || [ "$lines" -gt 500 ]' "runtime log bound missing"
require_text "$RUNTIME" 'refusing to displace the current notification server' "existing notification owner is not protected"
require_text "$RUNTIME" 'pgrep -x quickshell' "runtime process matching is not executable-bounded"
require_text "$UNIT" 'maho-notify run' "user service does not use managed runtime"
require_text "$ROOT/bin/maho-setup" 'maho-notify' "setup packaging does not know Maho Notify"
bash -n "$RUNTIME"
echo "PASS"

echo "ALL MAHO NOTIFY CONTRACTS PASS"
