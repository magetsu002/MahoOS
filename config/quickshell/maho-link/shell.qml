//@ pragma ShellId maho-link

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoLinkTheme { id: theme }
    MahoLinkState { id: wifi }
    BluetoothState { id: bluetooth }

    property bool presented: true
    property bool overlayOpen: false
    property bool dragging: false
    readonly property real surfaceMarginX: 24
    readonly property real surfaceMarginY: 20
    readonly property string initialMode:
        String(Quickshell.env("MAHO_LINK_MODE")) === "bluetooth" ? "bluetooth" : "wifi"

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
        // First-run placement still follows Maho Edge. Once the user moves the
        // connectivity surface, the normalized position below becomes authoritative.
        if (dockOccupiesRightSide)
            return margin
        return Math.max(margin, containerWidth - surfaceWidth - margin)
    }

    function maximumSurfaceX() {
        return Math.max(surfaceMarginX, overlay.width - linkSurface.width - surfaceMarginX)
    }

    function maximumSurfaceY() {
        return Math.max(surfaceMarginY, overlay.height - linkSurface.height - surfaceMarginY)
    }

    function applyPlacement() {
        const maxX = maximumSurfaceX()
        const maxY = maximumSurfaceY()

        if (linkPlacement.valid) {
            const spanX = Math.max(0, maxX - surfaceMarginX)
            const spanY = Math.max(0, maxY - surfaceMarginY)
            linkSurface.x = surfaceMarginX + spanX * clamp(Number(linkPlacement.normalizedX), 0, 1)
            linkSurface.y = surfaceMarginY + spanY * clamp(Number(linkPlacement.normalizedY), 0, 1)
            return
        }

        linkSurface.x = clamp(
            surfaceX(overlay.width, linkSurface.width, surfaceMarginX),
            surfaceMarginX,
            maxX
        )
        linkSurface.y = clamp(20, surfaceMarginY, maxY)
    }

    function persistPlacement() {
        const maxX = maximumSurfaceX()
        const maxY = maximumSurfaceY()
        linkSurface.x = clamp(linkSurface.x, surfaceMarginX, maxX)
        linkSurface.y = clamp(linkSurface.y, surfaceMarginY, maxY)

        const spanX = Math.max(0, maxX - surfaceMarginX)
        const spanY = Math.max(0, maxY - surfaceMarginY)
        linkPlacement.normalizedX = spanX > 0 ? (linkSurface.x - surfaceMarginX) / spanX : 0.5
        linkPlacement.normalizedY = spanY > 0 ? (linkSurface.y - surfaceMarginY) / spanY : 0.5
        linkPlacement.valid = true
    }

    FileView {
        path: root.stateBase + "/quickshell/by-shell/maho-shell/dock.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: {
            reload()
            if (!linkPlacement.valid && root.overlayOpen)
                Qt.callLater(root.applyPlacement)
        }

        JsonAdapter {
            id: dockState
            property int version: 1
            property string edge: "top"
            property real position: 0.5
        }
    }

    FileView {
        path: Quickshell.statePath("link-position.json")
        blockLoading: true
        onAdapterUpdated: writeAdapter()

        JsonAdapter {
            id: linkPlacement
            property int version: 1
            property bool valid: false
            property real normalizedX: 0.5
            property real normalizedY: 0.5
        }
    }

    function revealWifiSurface() {
        if (!overlayOpen || initialMode !== "wifi" || !wifi.statusReady || linkSurface.shown)
            return
        applyPlacement()
        linkSurface.shown = true
        linkSurface.forceActiveFocus()
    }

    function showOverlay() {
        closeTimer.stop()
        presented = true
        overlayOpen = true
        linkSurface.section = root.initialMode
        linkSurface.page = "main"
        linkSurface.shown = false
        applyPlacement()

        if (root.initialMode === "bluetooth") {
            linkSurface.shown = true
            linkSurface.forceActiveFocus()
            bluetooth.refresh()
        } else {
            // Do not paint default/offline placeholders as truth. Status is a
            // fast NetworkManager query; nearby-network discovery is independent.
            wifi.refresh()
            revealWifiSurface()
        }
    }

    function closeOverlay() {
        if (!overlayOpen)
            return
        overlayOpen = false
        linkSurface.shown = false
        closeTimer.restart()
    }

    Connections {
        target: wifi
        function onStatusReadyChanged() { root.revealWifiSurface() }
    }

    Component.onCompleted: openDelay.restart()

    Timer {
        id: openDelay
        interval: 12
        onTriggered: root.showOverlay()
    }

    Timer {
        id: closeTimer
        interval: 175
        onTriggered: {
            root.presented = false
            Qt.quit()
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
        focusable: root.overlayOpen
        exclusionMode: ExclusionMode.Ignore
        visible: root.presented

        onWidthChanged: {
            if (root.overlayOpen && !root.dragging)
                Qt.callLater(root.applyPlacement)
        }
        onHeightChanged: {
            if (root.overlayOpen && !root.dragging)
                Qt.callLater(root.applyPlacement)
        }

        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "maho-link"

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.overlayOpen ? 0.16 : 0)
            Behavior on color { ColorAnimation { duration: 170 } }
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.overlayOpen
            onClicked: root.closeOverlay()
        }

        MahoLink {
            id: linkSurface
            x: root.surfaceX(overlay.width, width, 24)
            y: 20
            theme: theme
            wifi: wifi
            bluetooth: bluetooth
            availableHeight: overlay.height
            section: root.initialMode
            shown: false
            onHeightChanged: {
                if (root.overlayOpen && !root.dragging)
                    Qt.callLater(root.applyPlacement)
            }
            onCloseRequested: root.closeOverlay()
        }

        // The title strip is deliberately the only drag target. It sits between
        // Back on the left and Wi-Fi toggle/Close on the right, so every existing
        // control keeps its original pointer contract.
        MouseArea {
            id: linkDragArea
            z: 20
            x: linkSurface.x + 64
            y: linkSurface.y + 18
            width: Math.max(80, linkSurface.width - 184)
            height: 40
            enabled: root.overlayOpen && linkSurface.shown
            hoverEnabled: true
            cursorShape: Qt.SizeAllCursor
            drag.target: linkSurface
            drag.axis: Drag.XAndYAxis
            drag.minimumX: root.surfaceMarginX
            drag.maximumX: root.maximumSurfaceX()
            drag.minimumY: root.surfaceMarginY
            drag.maximumY: root.maximumSurfaceY()
            onPressed: root.dragging = true
            onReleased: {
                root.dragging = false
                root.persistPlacement()
            }
            onCanceled: {
                root.dragging = false
                root.persistPlacement()
            }
        }
    }
}
