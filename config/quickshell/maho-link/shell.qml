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
    // Link deliberately owns no compositor blur surface. Hyprland blur
    // left a rounded stale-damage footprint after dismissal on both Wi-Fi and
    // Bluetooth. The material is fully rendered in QML instead.
    property bool presented: false
    property bool overlayOpen: false
    property bool dragging: false
    property bool placementReady: false
    property bool placementValid: false
    property bool placementLoadPending: false
    property bool placementApplied: false
    property bool placementSavePending: false
    property bool closeAfterPlacementSave: false
    readonly property string runtimeIdentity: Quickshell.env("MAHO_RUNTIME_IDENTITY")
    property string modeAfterPlacementSave: ""
    property real requestedPlacementX: -1
    property real requestedPlacementY: -1
    readonly property real surfaceMarginX: 24
    readonly property real surfaceMarginY: 20
    readonly property bool bootstrapGeometryReady:
        overlay.width >= linkSurface.width + (surfaceMarginX * 2)
        && overlay.height >= linkSurface.height + (surfaceMarginY * 2)
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
        placementApplied = true
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
        placementApplied = false
        if (!bootstrapGeometryReady) {
            placementLoadPending = true
            return
        }
        placementLoadPending = false
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

    function resumePendingPlacementLoad() {
        if (placementLoadPending && !placementLoad.running && bootstrapGeometryReady)
            requestPlacementLoad()
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
        if (!presented || !placementReady || linkSurface.shown)
            return
        if (activeMode === "wifi" && !wifi.statusReady)
            return

        // Resolve placement against authoritative screen geometry while the
        // foreground material window is still completely unmapped. Only after
        // coordinates are applied may Link enter the compositor, preventing a
        // one-frame default-position flash.
        applyPlacement()
        linkSurface.shown = true
        overlayOpen = true
        linkSurface.forceActiveFocus()
    }

    function showMode(mode, reloadPlacement) {
        const requestedMode = String(mode) === "bluetooth" ? "bluetooth" : "wifi"
        closeTimer.stop()
        idleRetireTimer.stop()
        closeAfterPlacementSave = false
        presented = true
        if (placementSave.running || placementSavePending) {
            modeAfterPlacementSave = requestedMode !== activeMode ? requestedMode : ""
            return true
        }
        const modeChanged = requestedMode !== activeMode

        // Hide the old geometry before switching section. Bluetooth is taller
        // than compact Wi-Fi, so switching section while visible can paint a
        // growing second edge. Hide first; hidden geometry now snaps instantly
        // to its final size before the short entrance animation.
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
        if (!presented)
            return
        modeAfterPlacementSave = ""
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
        // Keep the mapped surface alive just long enough for the restrained
        // material fade to finish. Pointer masks are removed immediately by
        // overlayOpen=false, so this does not leave an invisible hit target.
        interval: 120
        onTriggered: {
            root.presented = false
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

    // Full-screen dismissal/dim plane. This surface is intentionally never
    // blurred; it exists only to darken the desktop slightly and catch clicks
    // outside Link.
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
        visible: root.presented
        mask: Region { item: root.overlayOpen ? dimPlane : null }

        onWidthChanged: {
            if (root.placementLoadPending)
                Qt.callLater(root.resumePendingPlacementLoad)
            if (root.overlayOpen && !root.dragging)
                Qt.callLater(root.applyPlacement)
        }
        onHeightChanged: {
            if (root.placementLoadPending)
                Qt.callLater(root.resumePendingPlacementLoad)
            if (root.overlayOpen && !root.dragging)
                Qt.callLater(root.applyPlacement)
        }

        // The catcher must stay below the foreground material. Keeping both
        // on Overlay lets the full-screen catcher win pointer ownership.
        WlrLayershell.layer: WlrLayer.Top
        WlrLayershell.namespace: "maho-link-catcher"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

        Rectangle {
            id: dimPlane
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.overlayOpen ? 0.075 : 0)
            Behavior on color {
                ColorAnimation {
                    duration: root.overlayOpen ? 64 : 0
                    easing.type: Easing.OutCubic
                }
            }
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.overlayOpen
            onClicked: root.closeOverlay()
        }
    }

    // Foreground material surface. Hyprland blur is alpha-masked to this
    // rounded card, mirroring Notify's proven material architecture.
    PanelWindow {
        id: materialOverlay

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
        // Unlike the transparent catcher/bootstrap window, the foreground
        // material must not map until applyPlacement() has committed final
        // coordinates for this launch.
        visible: root.presented && root.placementApplied
        mask: Region { item: root.overlayOpen ? linkSurface : null }

        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "maho-link"
        WlrLayershell.keyboardFocus: root.overlayOpen
            ? WlrKeyboardFocus.Exclusive
            : WlrKeyboardFocus.None

        MahoLink {
            id: linkSurface
            x: 0
            y: 0
            theme: theme
            wifi: wifi
            bluetooth: bluetooth
            // Size hidden Link from the already-mapped transparent bootstrap
            // surface, so materialOverlay itself never needs to map for geometry.
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
            z: 600
            x: linkSurface.x + 60
            y: linkSurface.y + 16
            width: Math.max(100, linkSurface.width - 220)
            height: 48
            enabled: root.overlayOpen && linkSurface.shown
            hoverEnabled: true
            preventStealing: true
            cursorShape: Qt.SizeAllCursor
            drag.target: linkSurface
            drag.axis: Drag.XAndYAxis
            drag.threshold: 2
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
