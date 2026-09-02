//@ pragma ShellId maho-notify

import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
    id: root

    property bool centerOpen: false
    property bool centerPresented: false

    readonly property string stateBase: {
        const configured = Quickshell.env("XDG_STATE_HOME")
        return configured && String(configured) !== ""
            ? String(configured)
            : Quickshell.env("HOME") + "/.local/state"
    }
    readonly property string dockEdge:
        dockState.edge === "left" || dockState.edge === "right"
            || dockState.edge === "top" || dockState.edge === "bottom"
            ? dockState.edge : "top"

    function surfaceX(containerWidth, surfaceWidth, margin) {
        if (dockEdge === "right")
            return margin
        return Math.max(margin, containerWidth - surfaceWidth - margin)
    }

    FileView {
        path: root.stateBase + "/quickshell/by-shell/maho-shell/dock.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: reload()

        JsonAdapter {
            id: dockState
            property int version: 1
            property string edge: "top"
            property real position: 0.5
        }
    }

    NotifyTheme { id: theme }
    AppIdentityResolver { id: appIdentityResolver }
    NotificationModel { id: notificationModel }
    HistoryModel {
        id: historyModel
        identityResolver: appIdentityResolver
        onLoadedChanged: {
            if (loaded && root.centerOpen)
                markAllRead()
        }
    }

    NotificationService {
        id: notificationService
        onNotificationReceived: notification => {
            historyModel.record(notification)
            notificationModel.enqueue(notification, historyModel.dndEnabled)
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

        function livePopupCount(): int {
            return notificationModel.livePopupCount
        }

        function droppedPopupCount(): int {
            return notificationModel.droppedPopupCount
        }

        function suppressedPopupCount(): int {
            return notificationModel.suppressedPopupCount
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

        function dndStatus(): bool {
            return historyModel.dndEnabled
        }

        function setDnd(enabled: bool): bool {
            return historyModel.setDnd(enabled)
        }

        function toggleDnd(): bool {
            return historyModel.toggleDnd()
        }

        function openCenter(): bool {
            root.openCenter()
            return true
        }

        function closeCenter(): bool {
            root.closeCenter()
            return true
        }

        function centerStatus(): bool {
            return root.centerOpen
        }

        function dismissFirst(): bool {
            return notificationModel.dismissFirst()
        }

        function invokeFirstAction(): bool {
            return notificationModel.invokeFirstAction()
        }
    }

    function openCenter() {
        centerCloseDelay.stop()
        centerPresented = true
        centerOpen = true
        centerSurface.timeReference = new Date()
        historyModel.markAllRead()
        centerSurface.forceActiveFocus()
    }

    function closeCenter() {
        centerOpen = false
        centerCloseDelay.restart()
    }

    Timer {
        id: centerCloseDelay
        interval: 170
        onTriggered: root.centerPresented = false
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
            x: root.surfaceX(overlay.width, width, 18)
            y: 18
            theme: theme
            notificationModel: notificationModel
            identityResolver: appIdentityResolver
        }
    }

    PanelWindow {
        id: centerOverlay

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        color: "transparent"
        aboveWindows: true
        focusable: root.centerOpen
        exclusionMode: ExclusionMode.Ignore
        visible: root.centerPresented
        mask: Region { item: centerSurface }

        NotificationCenter {
            id: centerSurface
            x: root.surfaceX(centerOverlay.width, width, 18)
            y: 18
            theme: theme
            historyModel: historyModel
            identityResolver: appIdentityResolver
            availableHeight: centerOverlay.height
            shown: root.centerOpen
            onCloseRequested: root.closeCenter()
        }
    }
}
