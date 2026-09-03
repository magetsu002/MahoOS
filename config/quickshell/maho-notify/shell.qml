//@ pragma ShellId maho-notify

import QtQuick
import Quickshell
import Quickshell.Io

ShellRoot {
    id: root

    property bool centerOpen: false
    property bool centerPresented: false
    property bool centerDragging: false
    readonly property real centerMarginX: 18
    readonly property real centerMarginY: 18

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
    readonly property real dockPosition: {
        const numeric = Number(dockState.position)
        if (!isFinite(numeric))
            return 0.5
        return Math.max(0.08, Math.min(0.92, numeric))
    }
    readonly property bool dockOccupiesRightSide:
        dockEdge === "right"
            || ((dockEdge === "top" || dockEdge === "bottom") && dockPosition > 0.5)

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function surfaceX(containerWidth, surfaceWidth, margin) {
        if (dockOccupiesRightSide)
            return margin
        return Math.max(margin, containerWidth - surfaceWidth - margin)
    }

    function maximumCenterX() {
        return Math.max(centerMarginX, centerOverlay.width - centerSurface.width - centerMarginX)
    }

    function maximumCenterY() {
        return Math.max(centerMarginY, centerOverlay.height - centerSurface.height - centerMarginY)
    }

    function applyCenterPlacement() {
        const maxX = maximumCenterX()
        const maxY = maximumCenterY()

        if (centerPlacement.valid) {
            const spanX = Math.max(0, maxX - centerMarginX)
            const spanY = Math.max(0, maxY - centerMarginY)
            centerSurface.x = centerMarginX + spanX * clamp(Number(centerPlacement.normalizedX), 0, 1)
            centerSurface.y = centerMarginY + spanY * clamp(Number(centerPlacement.normalizedY), 0, 1)
            return
        }

        centerSurface.x = clamp(
            surfaceX(centerOverlay.width, centerSurface.width, centerMarginX),
            centerMarginX,
            maxX
        )
        centerSurface.y = clamp(centerMarginY, centerMarginY, maxY)
    }

    function persistCenterPlacement() {
        const maxX = maximumCenterX()
        const maxY = maximumCenterY()
        centerSurface.x = clamp(centerSurface.x, centerMarginX, maxX)
        centerSurface.y = clamp(centerSurface.y, centerMarginY, maxY)

        const spanX = Math.max(0, maxX - centerMarginX)
        const spanY = Math.max(0, maxY - centerMarginY)
        centerPlacement.normalizedX = spanX > 0 ? (centerSurface.x - centerMarginX) / spanX : 0.5
        centerPlacement.normalizedY = spanY > 0 ? (centerSurface.y - centerMarginY) / spanY : 0.5
        centerPlacement.valid = true
    }

    FileView {
        path: root.stateBase + "/quickshell/by-shell/maho-shell/dock.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: {
            reload()
            if (!centerPlacement.valid && root.centerOpen)
                Qt.callLater(root.applyCenterPlacement)
        }

        JsonAdapter {
            id: dockState
            property int version: 1
            property string edge: "top"
            property real position: 0.5
        }
    }

    FileView {
        path: Quickshell.statePath("center-position.json")
        blockLoading: true
        onAdapterUpdated: writeAdapter()

        JsonAdapter {
            id: centerPlacement
            property int version: 1
            property bool valid: false
            property real normalizedX: 0.5
            property real normalizedY: 0.5
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
        Qt.callLater(root.applyCenterPlacement)
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

        onWidthChanged: {
            if (root.centerOpen && !root.centerDragging)
                Qt.callLater(root.applyCenterPlacement)
        }
        onHeightChanged: {
            if (root.centerOpen && !root.centerDragging)
                Qt.callLater(root.applyCenterPlacement)
        }

        NotificationCenter {
            id: centerSurface
            x: root.surfaceX(centerOverlay.width, width, 18)
            y: 18
            theme: theme
            historyModel: historyModel
            identityResolver: appIdentityResolver
            availableHeight: centerOverlay.height
            shown: root.centerOpen
            onHeightChanged: {
                if (root.centerOpen && !root.centerDragging)
                    Qt.callLater(root.applyCenterPlacement)
            }
            onCloseRequested: root.closeCenter()
        }

        // Only the quiet title region is draggable. The notification mark,
        // unread badge and close button keep their existing click semantics.
        MouseArea {
            id: centerDragArea
            z: 20
            x: centerSurface.x + 60
            y: centerSurface.y + 16
            width: Math.max(100, centerSurface.width - 220)
            height: 48
            enabled: root.centerOpen
            hoverEnabled: true
            cursorShape: Qt.SizeAllCursor
            drag.target: centerSurface
            drag.axis: Drag.XAndYAxis
            drag.minimumX: root.centerMarginX
            drag.maximumX: root.maximumCenterX()
            drag.minimumY: root.centerMarginY
            drag.maximumY: root.maximumCenterY()
            onPressed: root.centerDragging = true
            onReleased: {
                root.centerDragging = false
                root.persistCenterPlacement()
            }
            onCanceled: {
                root.centerDragging = false
                root.persistCenterPlacement()
            }
        }
    }
}
