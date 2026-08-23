//@ pragma ShellId maho-shell

import QtQuick
import QtQuick.Shapes
import Quickshell
import Quickshell.Hyprland

ShellRoot {
    id: root

    MahoTheme { id: theme }
    Audio { id: audio }
    Brightness { id: brightness }
    SystemState { id: system }

    property bool expanded: false
    property bool closing: false
    property bool controlVisible: false
    property bool workspaceFlash: false
    property int lastWorkspace: 0
    property int surfaceHeight: 40
    property date now: new Date()

    readonly property int activeWorkspace:
        Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : 0

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

        let index = result.indexOf(activeWorkspace)
        if (index < 0)
            index = 0

        let start = Math.max(0, index - 2)
        start = Math.min(start, result.length - 5)
        return result.slice(start, start + 5)
    }

    function openPanel() {
        closeMorphTimer.stop()
        closeSurfaceTimer.stop()
        closing = false
        surfaceHeight = island.expandedHeight + 2
        expanded = true
        controlVisible = true
    }

    function closePanel() {
        if (!expanded || closing)
            return

        // First remove the dense control content while the full silhouette is
        // still present. Only after that short fade do we morph the physical
        // island back to its collapsed shape. This prevents the clipped little
        // rectangle that used to flash during close.
        closing = true
        controlVisible = false
        closeMorphTimer.restart()
    }

    function runShell(command) {
        Quickshell.execDetached(["bash", "-lc", command])
    }

    Component.onCompleted: lastWorkspace = activeWorkspace

    Connections {
        target: Hyprland
        function onFocusedWorkspaceChanged() {
            const current = Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : 0

            if (root.lastWorkspace > 0 && current > 0 && current !== root.lastWorkspace) {
                root.workspaceFlash = true
                workspaceTimer.restart()
            }

            root.lastWorkspace = current
        }
    }

    Timer {
        id: workspaceTimer
        interval: 1150
        onTriggered: root.workspaceFlash = false
    }

    Timer {
        id: closeMorphTimer
        interval: 135
        onTriggered: {
            if (!root.closing)
                return

            root.expanded = false
            root.closing = false
            closeSurfaceTimer.restart()
        }
    }

    Timer {
        id: closeSurfaceTimer
        interval: 430
        onTriggered: {
            if (!root.expanded && !root.closing)
                root.surfaceHeight = 40
        }
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

        anchors {
            top: true
            left: true
            right: true
        }

        implicitHeight: root.surfaceHeight
        color: "transparent"
        aboveWindows: true
        focusable: false
        exclusiveZone: 40

        mask: Region { item: island }

        Item {
            id: island

            readonly property real wing: 14
            readonly property real bodyRadius: root.expanded ? 24 : 18
            readonly property int expandedHeight: Math.ceil(controlCenter.implicitHeight + 34)

            property color shellFill: theme.alpha(theme.surfaceHigh, root.expanded ? 0.978 : 0.958)
            property color shellStroke: theme.alpha(theme.outline, root.expanded ? 0.28 : 0.18)

            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter

            width: root.expanded
                ? 430
                : ((audio.overlayOpen || brightness.overlayOpen)
                    ? 250
                    : (root.workspaceFlash ? 205 : (collapsedView.hovered ? 190 : 176)))

            height: root.expanded ? expandedHeight : 40

            onExpandedHeightChanged: {
                if (root.expanded)
                    root.surfaceHeight = expandedHeight + 2
            }

            Behavior on width {
                NumberAnimation {
                    duration: 340
                    easing.type: Easing.OutBack
                    easing.overshoot: 0.38
                }
            }

            Behavior on height {
                NumberAnimation {
                    duration: 380
                    easing.type: Easing.OutBack
                    easing.overshoot: 0.24
                }
            }

            Behavior on shellFill { ColorAnimation { duration: 420; easing.type: Easing.OutCubic } }
            Behavior on shellStroke { ColorAnimation { duration: 360 } }

            Shape {
                id: silhouette
                anchors.fill: parent
                antialiasing: true
                layer.enabled: true
                layer.samples: 8
                layer.smooth: true

                ShapePath {
                    id: contour
                    fillColor: island.shellFill
                    strokeColor: island.shellStroke
                    strokeWidth: 1

                    readonly property real w: island.width
                    readonly property real h: island.height
                    readonly property real g: island.wing
                    readonly property real r: island.bodyRadius

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
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                width: root.expanded ? 310 : 94
                height: 1
                color: theme.foreground
                opacity: 0.05

                Behavior on width { NumberAnimation { duration: 320 } }
                Behavior on color { ColorAnimation { duration: 400 } }
            }

            Rectangle {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: root.expanded ? 7 : 3
                anchors.horizontalCenter: parent.horizontalCenter
                width: root.expanded ? 36 : (root.workspaceFlash ? 40 : 20)
                height: 2
                radius: 1
                color: theme.primary
                opacity: root.expanded ? 0.46 : 0.82

                Behavior on width { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 400 } }
                Behavior on opacity { NumberAnimation { duration: 180 } }
            }

            Item {
                id: content
                anchors.fill: parent
                anchors.leftMargin: island.wing + (root.expanded ? 18 : 9)
                anchors.rightMargin: island.wing + (root.expanded ? 18 : 9)
                clip: true

                CollapsedIsland {
                    id: collapsedView
                    anchors.fill: parent
                    theme: theme
                    audio: audio
                    brightness: brightness
                    system: system
                    workspaceIds: root.workspaceIds()
                    activeWorkspace: root.activeWorkspace
                    workspaceFlash: root.workspaceFlash
                    now: root.now
                    enabled: !root.expanded && !root.closing
                    opacity: root.expanded || root.closing ? 0 : 1
                    onOpenRequested: root.openPanel()

                    Behavior on opacity { NumberAnimation { duration: 150 } }
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
                    now: root.now
                    enabled: root.controlVisible
                    opacity: root.controlVisible ? 1 : 0

                    Behavior on opacity { NumberAnimation { duration: 125; easing.type: Easing.OutCubic } }

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

                    onLockRequested: Quickshell.execDetached(["hyprlock"])

                    onScreenshotRequested: root.runShell(
                        "if command -v grimblast >/dev/null; then grimblast copy area; "
                        + "elif command -v hyprshot >/dev/null; then hyprshot -m region --clipboard-only; fi"
                    )

                    onLauncherRequested: {
                        root.closePanel()
                        Quickshell.execDetached([
                            Quickshell.env("HOME") + "/.local/bin/maho-rice-launcher"
                        ])
                    }

                    onMediaPreviousRequested: Quickshell.execDetached(["playerctl", "previous"])
                    onMediaToggleRequested: Quickshell.execDetached(["playerctl", "play-pause"])
                    onMediaNextRequested: Quickshell.execDetached(["playerctl", "next"])
                }
            }
        }
    }
}
