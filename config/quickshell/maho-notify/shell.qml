//@ pragma ShellId maho-notify

import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
    id: root

    NotifyTheme { id: theme }
    NotificationModel { id: notificationModel }
    HistoryModel { id: historyModel }

    NotificationService {
        id: notificationService
        onNotificationReceived: notification => {
            historyModel.record(notification)
            notificationModel.enqueue(notification)
        }
    }

    IpcHandler {
        target: "notify"

        function visibleCount(): int {
            return notificationModel.visibleCount
        }

        function queuedCount(): int {
            return notificationModel.queuedCount
        }

        function historyCount(): int {
            return historyModel.retainedCount
        }

        function unreadCount(): int {
            return historyModel.unreadCount
        }

        function clearHistory(): bool {
            return historyModel.clearHistory()
        }

        function dismissFirst(): bool {
            return notificationModel.dismissFirst()
        }

        function invokeFirstAction(): bool {
            return notificationModel.invokeFirstAction()
        }
    }

    PanelWindow {
        id: overlay

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        color: "transparent"
        aboveWindows: true
        focusable: false
        exclusionMode: ExclusionMode.Ignore
        visible: notificationModel.visibleCount > 0
        mask: Region { item: popupStack }

        NotificationStack {
            id: popupStack
            x: Math.max(12, overlay.width - width - 18)
            y: 18
            theme: theme
            notificationModel: notificationModel
        }
    }
}
