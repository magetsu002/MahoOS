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
    LinkBackdrop {
        id: backdrop
        active: root.backdropActive
        shown: root.backdropVisible
    }

    // Keep compositor blur on its own stable plane. The old architecture put
    // blur on the same full-screen surface whose dim layer and Link card were
    // animating, so Hyprland continuously recomputed the blur mask during the
    // entrance motion. That reads as a second/ghost layer under both Wi-Fi and
    // Bluetooth. The backdrop now exists before foreground reveal, fades out
    // over one very short frame window, then unmaps completely.
    property bool backdropActive: true
    property bool backdropVisible: false
    property bool presented: false
    property bool overlayOpen: false
    property bool dragging: false
    property bool placementReady: false
    property bool placementValid: false
    property bool placementSavePending: false
    property bool closeAfterPlacementSave: false
    readonly property string runtimeIdentity: Quickshell.env("MAHO_RUNTIME_IDENTITY")
    property string modeAfterPlacementSave: ""
    property real requestedPlacementX: -1
    property real requestedPlacementY: -1
    readonly property real surfaceMarginX: 24
    readonly property real surfaceMarginY: 20
    property string activeMode:
        String(Quickshell.env("MAHO_LINK_MODE")) === "bluetooth" ? "bluetooth" : "wifi"

    readonly property string stateBase: {
        const configured = Quickshell.env("XDG_STATE_HOME")
        return configured && String(configured) !== ""
            ? String(configured)
            : Quickshell.env("HOME") + "/.local/state"
    }
    // One product-scoped file owns two independent coordinates: dragging Wi-Fi
    // never moves Bluetooth, and dragging Bluetooth never moves Wi-Fi.
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
            "--mode", activeMode,
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
            "--mode", activeMode,
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
            if (String(payload.mode) !== activeMode) {
                placementValid = false
                placementReady = false
                Qt.callLater(root.requestPlacementLoad)
                return
            }
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
            "--mode", activeMode,
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
            } else if (root.modeAfterPlacementSave !== "") {
                const nextMode = root.modeAfterPlacementSave
                root.modeAfterPlacementSave = ""
                root.showMode(nextMode, true)
            }
        }
    }

    function revealSurfaceWhenReady() {
        if (!overlayOpen || !placementReady || linkSurface.shown)
            return
        if (activeMode === "wifi" && !wifi.statusReady)
            return
        applyPlacement()
        linkSurface.closing = false
        linkSurface.shown = true
        linkSurface.forceActiveFocus()
    }

    function showMode(mode, reloadPlacement) {
        const requestedMode = String(mode) === "bluetooth" ? "bluetooth" : "wifi"
        closeTimer.stop()
        idleRetireTimer.stop()
        closeAfterPlacementSave = false
        backdropActive = true
        backdropVisible = false
        presented = true
        overlayOpen = true
        Qt.callLater(function() { root.backdropVisible = true })
        if (placementSave.running || placementSavePending) {
            modeAfterPlacementSave = requestedMode !== activeMode ? requestedMode : ""
            return true
        }
        const modeChanged = requestedMode !== activeMode

        // Hide the old geometry before switching section. Bluetooth is taller
        // than compact Wi-Fi, so switching section while visible can paint a
        // growing second edge. Hide first; hidden geometry now snaps instantly
        // to its final size before the short entrance animation.
        linkSurface.closing = true
        linkSurface.shown = false
        activeMode = requestedMode
        linkSurface.page = "main"

        if (reloadPlacement || modeChanged || !placementReady)
            requestPlacementLoad()
        else
            Qt.callLater(root.revealSurfaceWhenReady)

        if (root.activeMode === "bluetooth") {
            bluetooth.refresh()
            // Hidden Link geometry snaps to its final size, so Bluetooth can
            // reveal on the next event turn without a synthetic settle delay.
            Qt.callLater(root.revealSurfaceWhenReady)
        } else {
            // Do not paint default/offline placeholders as truth. Status is a
            // fast NetworkManager query; nearby-network discovery is independent.
            wifi.refresh()
            revealSurfaceWhenReady()
        }
        return true
    }

    function showOverlay() {
        showMode(activeMode, true)
    }

    function closeOverlay() {
        if (!overlayOpen)
            return
        modeAfterPlacementSave = ""
        backdropVisible = false
        backdropActive = false
        overlayOpen = false
        linkSurface.closing = true
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

    IpcHandler {
        target: "link"

        function showMode(mode: string): bool {
            return root.showMode(mode, false)
        }

        function close(): bool {
            root.closeOverlay()
            return true
        }

        function runtimeIdentity(): string { return root.runtimeIdentity }

        function retire(nextIdentity: string): bool {
            if (nextIdentity === root.runtimeIdentity)
                return false
            root.backdropVisible = false
            root.backdropActive = false
            root.overlayOpen = false
            root.presented = false
            retireTimer.restart()
            return true
        }
    }

    // Escape is an overlay-level command, not a child-focus command. The old
    // MahoLink-local Keys handler only worked reliably after pointer focus had
    // entered the surface. ApplicationShortcut keeps dismissal authoritative
    // regardless of which row, field, or blank area currently owns focus.
    Shortcut {
        sequence: "Escape"
        context: Qt.ApplicationShortcut
        enabled: root.overlayOpen
        onActivated: root.closeOverlay()
    }

    Component.onCompleted: openDelay.restart()

    Timer {
        id: retireTimer
        interval: 1
        onTriggered: Qt.quit()
    }

    Timer {
        id: openDelay
        interval: 1
        onTriggered: root.showOverlay()
    }

    Timer {
        id: closeTimer
        interval: 68
        onTriggered: {
            root.presented = false
            linkSurface.closing = false
            idleRetireTimer.restart()
        }
    }

    Timer {
        id: idleRetireTimer
        interval: 30000
        repeat: false
        onTriggered: {
            if (!root.presented && !root.overlayOpen)
                Qt.quit()
        }
    }

    PanelWindow {
        id: warmKeepalive

        anchors {
            top: true
            left: true
        }
        implicitWidth: 1
        implicitHeight: 1
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        focusable: false
        visible: true
        mask: Region {}

        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "maho-link-keepalive"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
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
        mask: Region { item: root.overlayOpen ? dimPlane : null }

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
        WlrLayershell.keyboardFocus: root.overlayOpen
            ? WlrKeyboardFocus.Exclusive
            : WlrKeyboardFocus.None

        Rectangle {
            id: dimPlane
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.overlayOpen ? 0.16 : 0)
            Behavior on color {
                ColorAnimation {
                    duration: root.overlayOpen ? 72 : 48
                    easing.type: Easing.OutCubic
                }
            }
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
            section: root.activeMode
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
