//@ pragma ShellId maho-shell

import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoTheme { id: theme }
    Audio { id: audio }
    Brightness { id: brightness }
    Battery { id: battery }
    SystemState { id: system }
    Media { id: media }
    DockState { id: dock }
    NotifyStatus { id: notifyBridge }

    property bool expanded: false
    property bool closing: false
    property bool controlVisible: false
    property bool workspaceFlash: false
    property int workspaceVisual: 0
    property int workspaceEventSerial: 0
    property date now: new Date()

    property bool dragActive: false
    property real dragOriginX: 0
    property real dragOriginY: 0
    property real dragX: 0
    property real dragY: 0
    property string dragCandidateEdge: dock.edge
    property real dragCandidatePosition: dock.position

    readonly property bool verticalDock: dock.edge === "left" || dock.edge === "right"
    readonly property bool horizontalDock: !verticalDock

    readonly property int activeWorkspace:
        Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : 0

    readonly property bool fullscreenActive:
        Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.hasFullscreen : false

    readonly property int displayedWorkspace:
        workspaceVisual > 0 ? workspaceVisual : activeWorkspace

    onFullscreenActiveChanged: {
        if (!fullscreenActive)
            return

        closeMorphTimer.stop()
        closeSecondaryTimer.stop()
        expanded = false
        closing = false
        controlVisible = false
        dragActive = false
    }

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function workspaceIds() {
        const source = Hyprland.workspaces.values
        let result = []

        for (let i = 0; i < source.length; ++i) {
            if (source[i].id > 0)
                result.push(source[i].id)
        }

        result.sort(function(a, b) { return a - b })

        if (result.length <= 5)
            return result

        let index = result.indexOf(displayedWorkspace)
        if (index < 0)
            index = 0

        let start = Math.max(0, index - 2)
        start = Math.min(start, result.length - 5)
        return result.slice(start, start + 5)
    }

    function edgeX(itemWidth) {
        if (dock.edge === "left")
            return 0
        if (dock.edge === "right")
            return Math.max(0, panel.width - itemWidth)

        const center = panel.width * dock.position
        return clamp(center - itemWidth / 2, 0, Math.max(0, panel.width - itemWidth))
    }

    function edgeY(itemHeight) {
        if (dock.edge === "top")
            return 0
        if (dock.edge === "bottom")
            return Math.max(0, panel.height - itemHeight)

        const center = panel.height * dock.position
        return clamp(center - itemHeight / 2, 0, Math.max(0, panel.height - itemHeight))
    }

    function nearestEdge(centerX, centerY) {
        const distances = {
            "top": centerY,
            "bottom": panel.height - centerY,
            "left": centerX,
            "right": panel.width - centerX
        }

        let best = "top"
        let bestDistance = distances.top

        for (const candidate of ["bottom", "left", "right"]) {
            if (distances[candidate] < bestDistance) {
                best = candidate
                bestDistance = distances[candidate]
            }
        }

        return best
    }

    function edgePosition(edge, centerX, centerY) {
        if (edge === "top" || edge === "bottom")
            return dock.clampPosition(centerX / Math.max(1, panel.width))
        return dock.clampPosition(centerY / Math.max(1, panel.height))
    }

    function beginDockDrag() {
        if (expanded || closing)
            return

        // Capture the resting geometry before switching x/y to the drag
        // bindings. Setting dragActive first makes edgeSurface read the default
        // dragX/dragY values and jump to 0,0 before its origin is recorded.
        const originX = edgeSurface.x
        const originY = edgeSurface.y
        dragOriginX = originX
        dragOriginY = originY
        dragX = originX
        dragY = originY
        dragCandidateEdge = dock.edge
        dragCandidatePosition = dock.position
        dragActive = true
    }

    function updateDockDrag(deltaX, deltaY) {
        if (!dragActive)
            return

        dragX = clamp(
            dragOriginX + deltaX,
            0,
            Math.max(0, panel.width - edgeSurface.width)
        )
        dragY = clamp(
            dragOriginY + deltaY,
            0,
            Math.max(0, panel.height - edgeSurface.height)
        )

        const centerX = dragX + edgeSurface.width / 2
        const centerY = dragY + edgeSurface.height / 2
        dragCandidateEdge = nearestEdge(centerX, centerY)
        dragCandidatePosition = edgePosition(dragCandidateEdge, centerX, centerY)
    }

    function finishDockDrag() {
        if (!dragActive)
            return

        const edge = dragCandidateEdge
        const position = dragCandidatePosition
        dragActive = false
        dock.setDock(edge, position)
    }

    function openPanel() {
        if (dragActive)
            return

        closeMorphTimer.stop()
        closeSecondaryTimer.stop()
        closing = false
        expanded = true
        controlVisible = true
    }

    function closePanel() {
        if (!expanded || closing)
            return

        closing = true
        controlVisible = false
        closeMorphTimer.restart()
    }

    function runShell(command) {
        Quickshell.execDetached(["bash", "-lc", command])
    }

    function openNotificationCenter() {
        closePanel()
        Quickshell.execDetached([
            Quickshell.env("HOME") + "/.local/bin/maho-notify",
            "center"
        ])
    }

    function requestLock() {
        closePanel()
        lockDelay.restart()
    }

    function requestCapture() {
        closePanel()
        captureDelay.restart()
    }

    function triggerWorkspaceChange(nextWorkspace) {
        if (nextWorkspace <= 0)
            return

        workspaceVisual = nextWorkspace
        workspaceEventSerial += 1
        workspaceFlash = true
        workspaceTimer.restart()
    }

    Component.onCompleted: workspaceVisual = activeWorkspace

    Connections {
        target: Hyprland

        // Hyprland socket2 is the animation authority. workspacev2 is emitted
        // for every user-requested workspace change, so every event receives a
        // new serial even while the previous workspace feedback is still live.
        function onRawEvent(event) {
            if (event.name !== "workspacev2")
                return

            const fields = event.parse(2)
            const current = parseInt(fields[0])

            if (!isNaN(current) && current > 0)
                root.triggerWorkspaceChange(current)

            Hyprland.refreshWorkspaces()
        }

        // Keep a fallback for startup/reconnect paths where the raw event was
        // not observed. The visual workspace check prevents duplicate pulses.
        function onFocusedWorkspaceChanged() {
            const current = Hyprland.focusedWorkspace
                ? Hyprland.focusedWorkspace.id
                : 0

            if (current > 0 && current !== root.workspaceVisual)
                root.triggerWorkspaceChange(current)
        }
    }

    Timer {
        id: workspaceTimer
        interval: 1150
        onTriggered: root.workspaceFlash = false
    }

    Timer {
        id: closeMorphTimer
        interval: 110
        onTriggered: {
            if (!root.closing)
                return

            // Horizontal docks fold height first while staying wide. Side docks
            // fold width first while staying tall. Only after that primary fold
            // finishes do we collapse the second axis into the resting Maho Edge.
            root.expanded = false
            closeSecondaryTimer.restart()
        }
    }

    Timer {
        id: closeSecondaryTimer
        interval: root.verticalDock ? 255 : 185
        onTriggered: {
            if (!root.closing)
                return
            root.closing = false
        }
    }

    Timer {
        id: lockDelay
        interval: 520
        onTriggered: root.runShell(
            "if command -v hyprlock >/dev/null 2>&1; then exec hyprlock; "
            + "else command -v notify-send >/dev/null 2>&1 && notify-send 'Maho Shell' 'hyprlock is not installed'; fi"
        )
    }

    Timer {
        id: captureDelay
        interval: 560
        onTriggered: root.runShell(
            "if command -v hyprshot >/dev/null 2>&1; then exec hyprshot -m region --clipboard-only; "
            + "elif command -v grimblast >/dev/null 2>&1; then exec grimblast copy area; "
            + "elif command -v notify-send >/dev/null 2>&1; then notify-send 'Maho Shell' 'No screenshot backend is installed'; fi"
        )
    }

    Timer {
        interval: 1000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.now = new Date()
    }

    PanelWindow {
        id: panel

        // Fullscreen applications own the entire focused workspace. Removing
        // the overlay window also removes its input region until fullscreen
        // ends; normal workspaces recreate the same global Edge surface.
        visible: !root.fullscreenActive

        // Full-screen geometry lets Maho Edge follow the pointer while the
        // input mask keeps every pixel outside the visible surface click-through.
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

        // WlrLayer.Top sits below fullscreen workspace content in Hyprland.
        // Maho Edge is global desktop chrome, so its visible/input surface must
        // remain on the overlay layer on every normal workspace.
        WlrLayershell.layer: WlrLayer.Overlay

        mask: Region { item: edgeSurface }

        Rectangle {
            visible: root.dragActive && root.dragCandidateEdge === "top"
            x: root.clamp(panel.width * root.dragCandidatePosition - width / 2, 8, panel.width - width - 8)
            y: 2
            width: 74
            height: 3
            radius: 2
            color: theme.primary
            opacity: 0.72
        }

        Rectangle {
            visible: root.dragActive && root.dragCandidateEdge === "bottom"
            x: root.clamp(panel.width * root.dragCandidatePosition - width / 2, 8, panel.width - width - 8)
            y: panel.height - height - 2
            width: 74
            height: 3
            radius: 2
            color: theme.primary
            opacity: 0.72
        }

        Rectangle {
            visible: root.dragActive && root.dragCandidateEdge === "left"
            x: 2
            y: root.clamp(panel.height * root.dragCandidatePosition - height / 2, 8, panel.height - height - 8)
            width: 3
            height: 74
            radius: 2
            color: theme.primary
            opacity: 0.72
        }

        Rectangle {
            visible: root.dragActive && root.dragCandidateEdge === "right"
            x: panel.width - width - 2
            y: root.clamp(panel.height * root.dragCandidatePosition - height / 2, 8, panel.height - height - 8)
            width: 3
            height: 74
            radius: 2
            color: theme.primary
            opacity: 0.72
        }

        Item {
            id: edgeSurface

            readonly property bool wideBody: root.expanded || root.closing
            readonly property real wing: 14
            readonly property real bodyRadius: wideBody ? 24 : 18
            readonly property int expandedHeight: Math.ceil(controlCenter.implicitHeight + 34)
            readonly property int horizontalIdleWidth:
                (audio.overlayOpen || brightness.overlayOpen)
                    ? 250
                    : (root.workspaceFlash ? 205 : (edgeView.hovered ? 190 : 176))
            readonly property int verticalIdleHeight:
                (audio.overlayOpen || brightness.overlayOpen)
                    ? 250
                    : (root.workspaceFlash ? 205 : (sideEdgeView.hovered ? 202 : 190))

            property color shellFill: theme.alpha(theme.surfaceHigh, wideBody ? 0.978 : 0.958)
            property color shellStroke: theme.alpha(theme.outline, wideBody ? 0.28 : 0.18)

            x: root.dragActive ? root.dragX : root.edgeX(width)
            y: root.dragActive ? root.dragY : root.edgeY(height)

            width: root.verticalDock
                ? (root.expanded ? 430 : 46)
                : (wideBody ? 430 : horizontalIdleWidth)

            height: root.verticalDock
                ? ((root.expanded || root.closing) ? expandedHeight : verticalIdleHeight)
                : (root.expanded ? expandedHeight : 40)

            Behavior on x {
                enabled: !root.dragActive
                NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
            }

            Behavior on y {
                enabled: !root.dragActive
                NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
            }

            Behavior on width {
                NumberAnimation {
                    duration: root.closing && root.verticalDock ? 170 : 240
                    easing.type: Easing.OutCubic
                }
            }

            Behavior on height {
                NumberAnimation {
                    duration: root.closing && root.horizontalDock ? 170 : 240
                    easing.type: Easing.OutCubic
                }
            }

            Behavior on shellFill { ColorAnimation { duration: 360; easing.type: Easing.OutCubic } }
            Behavior on shellStroke { ColorAnimation { duration: 300 } }

            Shape {
                id: silhouette
                anchors.centerIn: parent
                width: root.verticalDock ? parent.height : parent.width
                height: root.verticalDock ? parent.width : parent.height
                rotation: dock.edge === "bottom" ? 180
                    : (dock.edge === "left" ? -90
                        : (dock.edge === "right" ? 90 : 0))
                antialiasing: true
                layer.enabled: true
                layer.samples: 8
                layer.smooth: true

                ShapePath {
                    id: contour
                    fillColor: edgeSurface.shellFill
                    strokeColor: edgeSurface.shellStroke
                    strokeWidth: 1

                    readonly property real w: silhouette.width
                    readonly property real h: silhouette.height
                    readonly property real g: edgeSurface.wing
                    readonly property real r: edgeSurface.bodyRadius

                    startX: 0
                    startY: 0

                    PathArc {
                        x: contour.g
                        y: contour.g
                        radiusX: contour.g
                        radiusY: contour.g
                        direction: PathArc.Clockwise
                    }
                    PathLine { x: contour.g; y: contour.h - contour.r }
                    PathArc {
                        x: contour.g + contour.r
                        y: contour.h
                        radiusX: contour.r
                        radiusY: contour.r
                        direction: PathArc.Counterclockwise
                    }
                    PathLine { x: contour.w - contour.g - contour.r; y: contour.h }
                    PathArc {
                        x: contour.w - contour.g
                        y: contour.h - contour.r
                        radiusX: contour.r
                        radiusY: contour.r
                        direction: PathArc.Counterclockwise
                    }
                    PathLine { x: contour.w - contour.g; y: contour.g }
                    PathArc {
                        x: contour.w
                        y: 0
                        radiusX: contour.g
                        radiusY: contour.g
                        direction: PathArc.Clockwise
                    }
                    PathLine { x: 0; y: 0 }
                }
            }

            Rectangle {
                visible: dock.edge === "top"
                anchors.bottom: parent.bottom
                anchors.bottomMargin: edgeSurface.wideBody ? 7 : 3
                anchors.horizontalCenter: parent.horizontalCenter
                width: edgeSurface.wideBody ? 36 : (root.workspaceFlash ? 40 : 20)
                height: 2
                radius: 1
                color: theme.primary
                opacity: edgeSurface.wideBody ? 0.46 : 0.82
            }

            Rectangle {
                visible: dock.edge === "bottom"
                anchors.top: parent.top
                anchors.topMargin: edgeSurface.wideBody ? 7 : 3
                anchors.horizontalCenter: parent.horizontalCenter
                width: edgeSurface.wideBody ? 36 : (root.workspaceFlash ? 40 : 20)
                height: 2
                radius: 1
                color: theme.primary
                opacity: edgeSurface.wideBody ? 0.46 : 0.82
            }

            Rectangle {
                visible: dock.edge === "left"
                anchors.right: parent.right
                anchors.rightMargin: edgeSurface.wideBody ? 7 : 3
                anchors.verticalCenter: parent.verticalCenter
                width: 2
                height: edgeSurface.wideBody ? 36 : (root.workspaceFlash ? 40 : 20)
                radius: 1
                color: theme.primary
                opacity: edgeSurface.wideBody ? 0.46 : 0.82
            }

            Rectangle {
                visible: dock.edge === "right"
                anchors.left: parent.left
                anchors.leftMargin: edgeSurface.wideBody ? 7 : 3
                anchors.verticalCenter: parent.verticalCenter
                width: 2
                height: edgeSurface.wideBody ? 36 : (root.workspaceFlash ? 40 : 20)
                radius: 1
                color: theme.primary
                opacity: edgeSurface.wideBody ? 0.46 : 0.82
            }

            Item {
                id: content
                anchors.fill: parent
                anchors.leftMargin: edgeSurface.wideBody ? edgeSurface.wing + 18 : (root.verticalDock ? 5 : edgeSurface.wing + 9)
                anchors.rightMargin: edgeSurface.wideBody ? edgeSurface.wing + 18 : (root.verticalDock ? 5 : edgeSurface.wing + 9)
                anchors.topMargin: !edgeSurface.wideBody && root.verticalDock ? edgeSurface.wing + 6 : 0
                anchors.bottomMargin: !edgeSurface.wideBody && root.verticalDock ? edgeSurface.wing + 6 : 0
                clip: true

                EdgeBar {
                    id: edgeView
                    anchors.fill: parent
                    visible: !root.verticalDock
                    theme: theme
                    audio: audio
                    brightness: brightness
                    system: system
                    battery: battery
                    workspaceIds: root.workspaceIds()
                    activeWorkspace: root.displayedWorkspace
                    workspaceFlash: root.workspaceFlash
                    workspaceEventSerial: root.workspaceEventSerial
                    now: root.now
                    enabled: visible && !root.expanded && !root.closing && !root.dragActive
                    opacity: visible && !root.expanded && !root.closing ? 1 : 0
                    onOpenRequested: root.openPanel()

                    Behavior on opacity { NumberAnimation { duration: 130 } }
                }

                SideEdgeBar {
                    id: sideEdgeView
                    anchors.fill: parent
                    visible: root.verticalDock
                    theme: theme
                    audio: audio
                    brightness: brightness
                    system: system
                    battery: battery
                    workspaceIds: root.workspaceIds()
                    activeWorkspace: root.displayedWorkspace
                    workspaceFlash: root.workspaceFlash
                    workspaceEventSerial: root.workspaceEventSerial
                    now: root.now
                    enabled: visible && !root.expanded && !root.closing && !root.dragActive
                    opacity: visible && !root.expanded && !root.closing ? 1 : 0
                    onOpenRequested: root.openPanel()

                    Behavior on opacity { NumberAnimation { duration: 130 } }
                }

                ControlCenter {
                    id: controlCenter
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    theme: theme
                    audio: audio
                    brightness: brightness
                    system: system
                    battery: battery
                    media: media
                    notifyStatus: notifyBridge
                    now: root.now
                    enabled: root.controlVisible
                    opacity: root.controlVisible ? 1 : 0

                    Behavior on opacity { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }

                    onCloseRequested: root.closePanel()
                    onVolumeRequested: function(value) { audio.setVolume(value) }
                    onBrightnessRequested: function(value) { brightness.setValue(value) }

                    onWifiRequested: root.runShell("command -v nmtui >/dev/null && kitty -e nmtui")
                    onBluetoothRequested: root.runShell("command -v bluetoothctl >/dev/null && kitty -e bluetoothctl")

                    onWallpaperRequested: {
                        root.closePanel()
                        Quickshell.execDetached([
                            "bash",
                            Quickshell.env("HOME") + "/.local/bin/qs-wallpaper-picker"
                        ])
                    }

                    onLockRequested: root.requestLock()
                    onScreenshotRequested: root.requestCapture()

                    onLauncherRequested: {
                        root.closePanel()
                        Quickshell.execDetached([
                            Quickshell.env("HOME") + "/.local/bin/maho-rice-launcher"
                        ])
                    }

                    onMediaPreviousRequested: media.previous()
                    onMediaToggleRequested: media.toggle()
                    onMediaNextRequested: media.next()
                    onNotificationsRequested: root.openNotificationCenter()
                }
            }

            // Runtime-proven drag contract. Do not fold click semantics or
            // compositor reservation into this handler.
            DragHandler {
                id: dockDrag
                enabled: !root.expanded && !root.closing
                target: null
                acceptedButtons: Qt.LeftButton
                dragThreshold: 8
                cursorShape: active ? Qt.ClosedHandCursor : Qt.OpenHandCursor

                onActiveChanged: {
                    if (active)
                        root.beginDockDrag()
                    else
                        root.finishDockDrag()
                }

                onActiveTranslationChanged: {
                    if (active)
                        root.updateDockDrag(activeTranslation.x, activeTranslation.y)
                }
            }
        }
    }

    // Maho Edge owns a small piece of compositor layout at its resting edge.
    // During drag dock.edge is intentionally unchanged, so windows reflow only
    // once when the snapped edge is committed on release.
    DockReservation {
        dock: dock
        screen: panel.screen
        breathingRoom: 8
    }
}
