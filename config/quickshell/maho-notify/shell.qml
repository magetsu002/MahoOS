//@ pragma ShellId maho-notify

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    property bool centerOpen: false
    property bool centerPresented: false
    property bool centerDragging: false
    property bool adaptiveQuiet: false
    property string adaptiveContext: ""
    readonly property real centerMarginX: 16
    readonly property real centerMarginY: 46

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

    function centerSurfaceItem() {
        return centerLoader.item
    }

    function maximumCenterX() {
        const surface = centerSurfaceItem()
        const surfaceWidth = surface ? surface.width : 520
        return Math.max(centerMarginX, centerOverlay.width - surfaceWidth - centerMarginX)
    }

    function maximumCenterY() {
        const surface = centerSurfaceItem()
        const surfaceHeight = surface ? surface.height : 460
        return Math.max(centerMarginY, centerOverlay.height - surfaceHeight - centerMarginY)
    }

    function applyCenterPlacement() {
        const surface = centerSurfaceItem()
        if (!surface)
            return
        const maxX = maximumCenterX()
        const maxY = maximumCenterY()
        if (centerPlacement.valid) {
            const spanX = Math.max(0, maxX - centerMarginX)
            const spanY = Math.max(0, maxY - centerMarginY)
            surface.x = centerMarginX + spanX * clamp(Number(centerPlacement.normalizedX), 0, 1)
            surface.y = centerMarginY + spanY * clamp(Number(centerPlacement.normalizedY), 0, 1)
            return
        }
        surface.x = clamp(
            surfaceX(centerOverlay.width, surface.width, centerMarginX), centerMarginX, maxX
        )
        surface.y = centerMarginY
    }

    function persistCenterPlacement() {
        const surface = centerSurfaceItem()
        if (!surface)
            return
        const maxX = maximumCenterX()
        const maxY = maximumCenterY()
        surface.x = clamp(surface.x, centerMarginX, maxX)
        surface.y = clamp(surface.y, centerMarginY, maxY)
        const spanX = Math.max(0, maxX - centerMarginX)
        const spanY = Math.max(0, maxY - centerMarginY)
        centerPlacement.normalizedX = spanX > 0 ? (surface.x - centerMarginX) / spanX : 0.5
        centerPlacement.normalizedY = spanY > 0 ? (surface.y - centerMarginY) / spanY : 0.5
        centerPlacement.valid = true
    }

    FileView {
        path: root.stateBase + "/quickshell/by-shell/maho-shell/dock.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: {
            reload()
            if (!centerPlacement.valid && root.centerOpen && !root.centerDragging)
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
    UpdateAttention { }
    AppIdentityResolver { id: appIdentityResolver }
    NotificationModel { id: notificationModel }
    HistoryModel {
        id: historyModel
        identityResolver: appIdentityResolver
        onDndEnabledChanged: {
            if (!dndEnabled && !root.adaptiveQuiet)
                releaseUntilFree()
        }
        onReplayRequested: entry => {
            if (notificationModel.showHistoryEntry(entry))
                root.closeCenter()
        }
    }

    NotificationService {
        id: notificationService
        onNotificationReceived: notification => {
            const decision = historyModel.presentationDecision(
                notification, historyModel.dndEnabled, root.adaptiveQuiet, root.adaptiveContext
            )
            historyModel.record(
                notification, decision.held, decision.holdReason, decision.deliveryMode
            )
            notificationModel.enqueue(notification, decision.suppress)
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

        function adaptiveQuietStatus(): bool {
            return root.adaptiveQuiet
        }

        function adaptiveQuietContext(): string {
            return root.adaptiveContext
        }

        function setAdaptiveQuietContext(context: string): string {
            const clean = String(context || "")
            root.adaptiveContext = clean === "Gaming" || clean === "Media" || clean === "Focus" ? clean : ""
            if (root.adaptiveContext !== "Gaming")
                historyModel.releaseGamingHolds()
            return root.adaptiveContext
        }

        function setAdaptiveQuiet(enabled: bool): bool {
            root.adaptiveQuiet = Boolean(enabled)
            if (!root.adaptiveQuiet) {
                root.adaptiveContext = ""
                historyModel.releaseGamingHolds()
                if (!historyModel.dndEnabled)
                    historyModel.releaseUntilFree()
            }
            return root.adaptiveQuiet
        }

        function setAdaptiveQuietState(enabled: bool, context: string): bool {
            setAdaptiveQuietContext(context)
            return setAdaptiveQuiet(enabled)
        }

        function historyPresentationAction(entryId: string, action: string): bool {
            return historyModel.presentationAction(entryId, action, root.adaptiveQuiet, root.adaptiveContext)
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

        function centerLoaded(): bool {
            return centerLoader.item !== null
        }

        function dismissFirst(): bool {
            return notificationModel.dismissFirst()
        }

        function invokeFirstAction(): bool {
            return notificationModel.invokeFirstAction()
        }
    }

    function openCenter() {
        centerRevealDelay.stop()

        // Load the center tree only while it is presented. Keep the first frame
        // transparent, initialize the accepted UI state, then reveal it once the
        // synchronous loader has produced the surface.
        centerOpen = false
        centerPresented = true
        Qt.callLater(function() {
            const surface = root.centerSurfaceItem()
            if (!surface)
                return
            surface.timeReference = new Date()
            surface.openMenuId = ""
            surface.controlMenuOpen = false
            root.applyCenterPlacement()
            centerRevealDelay.restart()
        })
    }

    onAdaptiveQuietChanged: {
        if (!adaptiveQuiet) {
            historyModel.releaseGamingHolds()
            if (!historyModel.dndEnabled)
                historyModel.releaseUntilFree()
        }
    }

    function closeCenter() {
        centerRevealDelay.stop()
        centerDragging = false
        // Blur belongs to this foreground layer, so unmapping the center removes
        // material and diffusion in the same compositor frame.
        centerOpen = false
        centerPresented = false
    }

    Timer {
        id: centerRevealDelay
        interval: 16
        onTriggered: {
            const surface = root.centerSurfaceItem()
            if (!surface)
                return
            root.centerOpen = true
            Qt.callLater(root.applyCenterPlacement)
            surface.forceActiveFocus()
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
        WlrLayershell.namespace: "maho-notify-popup"
        WlrLayershell.layer: WlrLayer.Overlay
        focusable: false
        exclusionMode: ExclusionMode.Ignore
        visible: notificationModel.presentationCount > 0
        mask: Region { item: popupStack }

        NotificationStack {
            id: popupStack
            x: root.surfaceX(overlay.width, width, 18)
            y: 18
            theme: theme
            notificationModel: notificationModel
            historyModel: historyModel
            identityResolver: appIdentityResolver
        }
    }

    // Two bounded rounded blur carriers compound diffusion only under Notify.
    // Unlike rectangular background-effect regions, these carriers preserve the rounded
    // alpha mask at the corners and can move with the panel without changing
    // the foreground material itself.
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
        WlrLayershell.namespace: "maho-notify-center"
        WlrLayershell.layer: WlrLayer.Overlay
        focusable: root.centerOpen
        exclusionMode: ExclusionMode.Ignore
        visible: root.centerPresented
        mask: Region { item: centerLoader.item }

        onWidthChanged: {
            if (root.centerOpen && !root.centerDragging)
                Qt.callLater(root.applyCenterPlacement)
        }
        onHeightChanged: {
            if (root.centerOpen && !root.centerDragging)
                Qt.callLater(root.applyCenterPlacement)
        }

        Loader {
            id: centerLoader
            active: root.centerPresented
            asynchronous: false
            onLoaded: Qt.callLater(root.applyCenterPlacement)

            sourceComponent: Component {
                NotificationCenter {
                    x: root.surfaceX(centerOverlay.width, width, root.centerMarginX)
                    y: root.centerMarginY
                    theme: theme
                    historyModel: historyModel
                    identityResolver: appIdentityResolver
                    adaptiveQuiet: root.adaptiveQuiet
                    adaptiveContext: root.adaptiveContext
                    availableHeight: centerOverlay.height
                    shown: root.centerOpen
                    onHeightChanged: {
                        if (root.centerOpen && !root.centerDragging)
                            Qt.callLater(root.applyCenterPlacement)
                    }
                    onCloseRequested: root.closeCenter()
                    onAdaptiveQuietStopRequested: {
                        root.adaptiveQuiet = false
                        root.adaptiveContext = ""
                        historyModel.releaseGamingHolds()
                        if (!historyModel.dndEnabled)
                            historyModel.releaseUntilFree()
                    }
                }
            }
        }

        // Header-only drag target: controls and notification cards keep their
        // own pointer behavior. The rounded compositor carriers stay active and
        // follow final panel geometry so material depth does not change mid-drag.
        MouseArea {
            id: centerDragArea
            z: 600
            x: centerLoader.item ? centerLoader.item.x + 60 : 0
            y: centerLoader.item ? centerLoader.item.y + 16 : 0
            width: centerLoader.item ? Math.max(100, centerLoader.item.width - 220) : 0
            height: 48
            enabled: root.centerOpen && centerLoader.item !== null
            hoverEnabled: true
            cursorShape: Qt.SizeAllCursor
            drag.target: centerLoader.item
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
