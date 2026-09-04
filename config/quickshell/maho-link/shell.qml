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
    property bool placementReady: false
    property bool placementValid: false
    property bool placementSavePending: false
    property bool closeAfterPlacementSave: false
    property real requestedPlacementX: -1
    property real requestedPlacementY: -1
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
    // Placement belongs to Maho Link as a product, not to whichever
    // Quickshell runtime copy happened to launch Wi-Fi or Bluetooth.
    // Keep one explicit XDG state file so both modes always converge.
    readonly property string linkPlacementPath: stateBase + "/maho/link-position.json"
    readonly property string legacyProductPlacementPath: stateBase + "/maho-link-position.json"
    readonly property string legacyShellPlacementPath:
        stateBase + "/quickshell/by-shell/maho-link/link-position.json"
    readonly property string positionHelperPath: Quickshell.env("MAHO_LINK_POSITION_HELPER")
    readonly property string geometryReportPath: Quickshell.env("MAHO_LINK_GEOMETRY_REPORT")
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

    function monitorName() {
        return overlay.screen && overlay.screen.name ? String(overlay.screen.name) : ""
    }

    function applyPlacement() {
        const maxX = maximumSurfaceX()
        const maxY = maximumSurfaceY()

        if (placementValid) {
            linkSurface.x = clamp(requestedPlacementX, surfaceMarginX, maxX)
            linkSurface.y = clamp(requestedPlacementY, surfaceMarginY, maxY)
        } else {
            linkSurface.x = clamp(
                surfaceX(overlay.width, linkSurface.width, surfaceMarginX),
                surfaceMarginX,
                maxX
            )
            linkSurface.y = clamp(20, surfaceMarginY, maxY)
        }
        reportAppliedGeometry()
    }

    function persistPlacement() {
        const maxX = maximumSurfaceX()
        const maxY = maximumSurfaceY()
        linkSurface.x = clamp(linkSurface.x, surfaceMarginX, maxX)
        linkSurface.y = clamp(linkSurface.y, surfaceMarginY, maxY)

        requestedPlacementX = linkSurface.x
        requestedPlacementY = linkSurface.y
        placementValid = true

        placementSavePending = true
        placementSave.command = [
            "python3", positionHelperPath, "save",
            "--path", linkPlacementPath,
            "--mode", initialMode,
            "--x", String(requestedPlacementX),
            "--y", String(requestedPlacementY),
            "--monitor", monitorName(),
            "--monitor-width", String(overlay.width),
            "--monitor-height", String(overlay.height)
        ]
        placementSave.running = true
        reportAppliedGeometry()
    }

    function requestPlacementLoad() {
        placementReady = false
        placementValid = false
        placementLoad.command = [
            "python3", positionHelperPath, "load",
            "--path", linkPlacementPath,
            "--legacy", legacyProductPlacementPath,
            "--legacy", legacyShellPlacementPath,
            "--mode", initialMode,
            "--monitor", monitorName(),
            "--monitor-width", String(overlay.width),
            "--monitor-height", String(overlay.height),
            "--surface-width", String(linkSurface.width),
            "--surface-height", String(linkSurface.height),
            "--margin-x", String(surfaceMarginX),
            "--margin-y", String(surfaceMarginY)
        ]
        placementLoad.running = true
    }

    function placementLoaded(text) {
        try {
            const payload = JSON.parse(text || "{}")
            placementValid = Boolean(payload.valid)
            if (placementValid) {
                requestedPlacementX = Number(payload.requested_x)
                requestedPlacementY = Number(payload.requested_y)
            }
        } catch (error) {
            placementValid = false
        }
        placementReady = true
        revealSurfaceWhenReady()
    }

    function reportAppliedGeometry() {
        if (!geometryReportPath || String(geometryReportPath) === "" || !placementValid)
            return
        Quickshell.execDetached([
            "python3", positionHelperPath, "report",
            "--path", geometryReportPath,
            "--mode", initialMode,
            "--requested-x", String(requestedPlacementX),
            "--requested-y", String(requestedPlacementY),
            "--x", String(linkSurface.x),
            "--y", String(linkSurface.y),
            "--width", String(linkSurface.width),
            "--height", String(linkSurface.height)
        ])
    }

    FileView {
        path: root.stateBase + "/quickshell/by-shell/maho-shell/dock.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: {
            reload()
            if (!root.placementValid && root.overlayOpen)
                Qt.callLater(root.applyPlacement)
        }

        JsonAdapter {
            id: dockState
            property int version: 1
            property string edge: "top"
            property real position: 0.5
        }
    }

    Process {
        id: placementLoad
        running: false
        stdout: StdioCollector {
            onStreamFinished: root.placementLoaded(text)
        }
    }

    Process {
        id: placementSave
        running: false

        onRunningChanged: {
            if (running || !root.placementSavePending)
                return
            root.placementSavePending = false
            if (root.closeAfterPlacementSave) {
                root.closeAfterPlacementSave = false
                closeTimer.restart()
            }
        }
    }

    function revealSurfaceWhenReady() {
        if (!overlayOpen || !placementReady || linkSurface.shown)
            return
        if (initialMode === "wifi" && !wifi.statusReady)
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
        requestPlacementLoad()

        if (root.initialMode === "bluetooth") {
            bluetooth.refresh()
        } else {
            // Do not paint default/offline placeholders as truth. Status is a
            // fast NetworkManager query; nearby-network discovery is independent.
            wifi.refresh()
            revealSurfaceWhenReady()
        }
    }

    function closeOverlay() {
        if (!overlayOpen)
            return
        overlayOpen = false
        linkSurface.shown = false
        if (placementSave.running || placementSavePending) {
            closeAfterPlacementSave = true
            return
        }
        closeTimer.restart()
    }

    Connections {
        target: wifi
        function onStatusReadyChanged() { root.revealSurfaceWhenReady() }
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
            x: 0
            y: 0
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
