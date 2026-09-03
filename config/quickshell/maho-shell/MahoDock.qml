import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland

PanelWindow {
    id: root

    required property var theme
    required property var dockModel
    required property var dockState

    anchors {
        bottom: true
    }

    margins {
        bottom: 28
    }

    // Stable Wayland carrier: all visual motion happens inside this surface so
    // the compositor never has to chase a resizing layer-shell window.
    implicitWidth: 720
    implicitHeight: 326
    color: "transparent"
    visible: dockModel.items.length > 0
    aboveWindows: true
    focusable: false
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "maho-dock"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    readonly property color accent: stableAccent(theme.semanticAccent)
    readonly property bool brightBackdrop: theme.semanticBackground.hslLightness > 0.52
    readonly property color smokedNeutral:
        theme.mix(theme.semanticSurfaceElevated, theme.semanticShadow, brightBackdrop ? 0.40 : 0.56)
    readonly property color shellMaterial:
        theme.mix(smokedNeutral, accent, 0.008)
    readonly property color shellFill:
        theme.alpha(shellMaterial, brightBackdrop ? 0.60 : 0.48)
    readonly property color shellFillRaised:
        theme.alpha(theme.mix(shellMaterial, theme.semanticSurfaceElevated, 0.12), brightBackdrop ? 0.68 : 0.55)
    readonly property color shellRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.27 : 0.21)
    readonly property color shellInnerRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.12 : 0.085)
    readonly property color shellSpecular:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.22 : 0.17)
    readonly property color shellReflection:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.075 : 0.052)
    readonly property color shellLowlight:
        theme.alpha(theme.semanticShadow, brightBackdrop ? 0.15 : 0.28)

    readonly property int dockHeight: 88
    readonly property int retractedHeight: 12
    readonly property int retractedWidth: 94
    readonly property int previewHeight: 220
    readonly property int previewWidth: 694
    readonly property int restingDockWidth: Math.max(300, dockRow.implicitWidth + 38)
    readonly property var previewWindows:
        previewItem && Array.isArray(previewItem.windows)
            ? previewItem.windows.slice(0, 3)
            : []

    readonly property var activeTop: Hyprland.activeToplevel
    readonly property var activeIpc:
        activeTop && activeTop.lastIpcObject ? activeTop.lastIpcObject : ({})
    readonly property bool activeWindowOccupiesDock: {
        if (!activeTop || !activeTop.activated)
            return false
        if (activeTop.wayland && activeTop.wayland.fullscreen)
            return true
        if (Number(activeIpc.fullscreen || 0) > 0)
            return true
        // Hyprland tiled clients consume the bottom work area. Floating clients
        // are left alone so a small dialog does not unnecessarily hide the Dock.
        return activeIpc.floating === false
    }

    property var hoverCandidate: null
    property var previewItem: null
    property bool previewOpen: false
    property bool dockHovering: false
    property real previewProgress: previewOpen ? 1 : 0

    property bool hoverLensVisible: false
    property real hoverLensX: 0

    readonly property bool retreatRequested:
        activeWindowOccupiesDock
        && !dockSurfaceHover.hovered
        && !previewOpen
        && previewProgress < 0.02
    property real dockRevealProgress: retreatRequested ? 0 : 1

    Behavior on previewProgress {
        NumberAnimation {
            duration: 360
            easing.type: Easing.OutCubic
        }
    }

    Behavior on dockRevealProgress {
        NumberAnimation {
            duration: 300
            easing.type: Easing.OutCubic
        }
    }

    function stableAccent(source) {
        const saturation = source.hsvSaturation
        if (saturation < 0.08)
            return theme.mix(theme.semanticForeground, theme.semanticSurfaceElevated, 0.38)
        const hue = source.hsvHue < 0 ? 0 : source.hsvHue
        return Qt.hsva(
            hue,
            Math.max(0.18, Math.min(0.58, saturation)),
            Math.max(0.60, Math.min(0.86, source.hsvValue)),
            1
        )
    }

    function armPreview(item) {
        root.dockHovering = true
        previewDismiss.stop()

        if (!item || !item.running || !item.windows || item.windows.length === 0) {
            hoverCandidate = null
            hoverIntent.stop()
            if (previewOpen)
                previewDismiss.restart()
            return
        }

        hoverCandidate = item
        if (previewOpen && previewItem && String(previewItem.id) === String(item.id))
            return
        hoverIntent.restart()
    }

    function leaveDockItem() {
        root.dockHovering = false
        hoverIntent.stop()
        previewDismiss.restart()
    }

    function openPreview(item) {
        if (!item || !item.running || !item.windows || item.windows.length === 0)
            return
        previewClear.stop()
        previewItem = item
        previewOpen = true
    }

    function closePreview() {
        if (!previewOpen)
            return
        previewOpen = false
        previewClear.restart()
    }

    function activateDockItem(item, newWindow) {
        closePreview()
        dockModel.activateItem(item, newWindow)
    }

    function showHoverLens(target) {
        hoverLensClear.stop()
        if (!target)
            return
        const center = target.mapToItem(dockShell, target.width / 2, target.height / 2)
        hoverLensX = center.x - hoverLens.width / 2
        hoverLensVisible = true
    }

    function hideHoverLensSoon() {
        hoverLensClear.restart()
    }

    Timer {
        id: hoverIntent
        interval: 620
        repeat: false
        onTriggered: root.openPreview(root.hoverCandidate)
    }

    Timer {
        id: hoverLensClear
        interval: 70
        repeat: false
        onTriggered: root.hoverLensVisible = false
    }

    Timer {
        id: previewDismiss
        interval: 260
        repeat: false
        onTriggered: {
            if (!previewHover.hovered && !root.dockHovering)
                root.closePreview()
        }
    }

    Timer {
        id: previewClear
        interval: 380
        repeat: false
        onTriggered: {
            if (!root.previewOpen)
                root.previewItem = null
        }
    }

    mask: Region {
        item: root.previewOpen || root.previewProgress > 0.02 ? materialBounds : dockShell
    }

    Item {
        id: materialBounds
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: root.previewWidth
        height: root.previewHeight + root.dockHeight + 12
    }

    Rectangle {
        id: previewDepth
        anchors.horizontalCenter: previewShell.horizontalCenter
        anchors.top: previewShell.top
        anchors.topMargin: 5
        width: previewShell.width + 4
        height: previewShell.height + 3
        radius: previewShell.radius + 2
        color: root.theme.alpha(root.theme.semanticShadow, 0.24)
        opacity: root.previewProgress * 0.74
    }

    Rectangle {
        id: previewShell
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: dockShell.top
        anchors.bottomMargin: 12
        width: root.restingDockWidth
            + (root.previewWidth - root.restingDockWidth) * root.previewProgress
        height: root.previewHeight * root.previewProgress
        radius: 29
        antialiasing: true
        color: root.shellFillRaised
        border.width: 1
        border.color: root.shellRim
        clip: true
        opacity: root.previewProgress
        transformOrigin: Item.Bottom
        scale: 0.982 + 0.018 * root.previewProgress

        Rectangle {
            anchors.fill: parent
            radius: previewShell.radius
            antialiasing: true
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.00
                    color: root.theme.alpha(root.theme.semanticForeground, 0.105)
                }
                GradientStop {
                    position: 0.12
                    color: root.theme.alpha(root.theme.semanticForeground, 0.032)
                }
                GradientStop {
                    position: 0.27
                    color: root.theme.alpha(root.accent, 0.010)
                }
                GradientStop { position: 0.62; color: "transparent" }
                GradientStop {
                    position: 1.00
                    color: root.theme.alpha(root.theme.semanticShadow, 0.20)
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            height: 18
            radius: 9
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.shellReflection }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.76
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: previewShell.radius - 1
            color: "transparent"
            border.width: 1
            border.color: root.shellInnerRim
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 32
            anchors.rightMargin: 32
            anchors.top: parent.top
            height: 1
            radius: 1
            color: root.shellSpecular
        }

        Rectangle {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: 34
            anchors.bottomMargin: 34
            width: 1
            color: root.theme.alpha(root.theme.semanticForeground, 0.045)
        }

        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.topMargin: 34
            anchors.bottomMargin: 34
            width: 1
            color: root.theme.alpha(root.theme.semanticForeground, 0.034)
        }

        Item {
            id: previewContent
            anchors.fill: parent
            opacity: Math.max(0, Math.min(1, (root.previewProgress - 0.16) / 0.84))
            y: 12 * (1 - root.previewProgress)

            Row {
                id: previewHeader
                anchors.top: parent.top
                anchors.topMargin: 17
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 9

                MahoDockAppIcon {
                    width: 24
                    height: 24
                    name: root.previewItem ? String(root.previewItem.name || "") : ""
                    entryId: root.previewItem ? String(root.previewItem.id || "") : ""
                    icon: root.previewItem ? String(root.previewItem.icon || "") : ""
                    iconPath: root.previewItem ? String(root.previewItem.iconPath || "") : ""
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.previewItem ? String(root.previewItem.name || "Application") : "Application"
                    color: root.theme.semanticForeground
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Row {
                id: previewRow
                anchors.top: previewHeader.bottom
                anchors.topMargin: 14
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 12

                Repeater {
                    model: root.previewWindows

                    MahoDockPreviewCard {
                        required property var modelData
                        theme: root.theme
                        accent: root.accent
                        windowData: modelData
                        appName: root.previewItem ? String(root.previewItem.name || "Application") : "Application"
                        appEntryId: root.previewItem ? String(root.previewItem.id || "") : ""
                        appIcon: root.previewItem ? String(root.previewItem.icon || "") : ""
                        appIconPath: root.previewItem ? String(root.previewItem.iconPath || "") : ""
                        active: root.previewOpen && root.previewProgress > 0.62
                        onActivated: function(windowData) {
                            root.closePreview()
                            root.dockModel.focusWindow(windowData)
                        }
                    }
                }
            }

            Row {
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 15
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 12

                Rectangle {
                    id: newWindowAction
                    visible: root.previewItem && !root.previewItem.temporary
                    width: 126
                    height: 30
                    radius: 15
                    color: root.theme.alpha(
                        root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, 0.020),
                        newWindowHover.hovered ? 0.62 : 0.48
                    )
                    border.width: 1
                    border.color: root.theme.alpha(
                        newWindowHover.hovered ? root.accent : root.theme.semanticForeground,
                        newWindowHover.hovered ? 0.19 : 0.075
                    )

                    Behavior on color {
                        ColorAnimation { duration: 180; easing.type: Easing.OutCubic }
                    }
                    Behavior on border.color {
                        ColorAnimation { duration: 180; easing.type: Easing.OutCubic }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: "New Window"
                        color: root.theme.semanticForeground
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }

                    HoverHandler {
                        id: newWindowHover
                        cursorShape: Qt.PointingHandCursor
                    }

                    TapHandler {
                        acceptedButtons: Qt.LeftButton
                        onTapped: {
                            if (root.previewItem)
                                root.activateDockItem(root.previewItem, true)
                        }
                    }
                }

                Rectangle {
                    width: 112
                    height: 30
                    radius: 15
                    color: root.theme.alpha(root.theme.semanticSurfaceElevated, 0.34)
                    border.width: 1
                    border.color: root.theme.alpha(root.theme.semanticForeground, 0.055)

                    Text {
                        anchors.centerIn: parent
                        text: root.previewItem
                            ? String(root.previewItem.windowCount || 0) + (Number(root.previewItem.windowCount || 0) === 1 ? " Window" : " Windows")
                            : "0 Windows"
                        color: root.theme.semanticForegroundMuted
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }
            }
        }

        HoverHandler {
            id: previewHover
            onHoveredChanged: {
                if (hovered)
                    previewDismiss.stop()
                else if (!root.dockHovering)
                    previewDismiss.restart()
            }
        }
    }

    Rectangle {
        id: dockDepth
        anchors.horizontalCenter: dockShell.horizontalCenter
        anchors.bottom: dockShell.bottom
        anchors.bottomMargin: -4
        width: dockShell.width + 6
        height: dockShell.height + 5
        radius: dockShell.radius + 3
        color: root.theme.alpha(root.theme.semanticShadow, 0.28)
        opacity: 0.46 + 0.38 * root.dockRevealProgress
    }

    Rectangle {
        id: dockShell
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: root.retractedWidth
            + (root.restingDockWidth - root.retractedWidth) * root.dockRevealProgress
        height: root.retractedHeight
            + (root.dockHeight - root.retractedHeight) * root.dockRevealProgress
        radius: 6 + 26 * root.dockRevealProgress
        antialiasing: true
        color: root.previewOpen
            ? root.theme.alpha(root.shellMaterial, root.brightBackdrop ? 0.63 : 0.51)
            : root.shellFill
        border.width: 1
        border.color: root.shellRim
        clip: true

        Behavior on color {
            ColorAnimation { duration: 320; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.fill: parent
            radius: dockShell.radius
            antialiasing: true
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.00
                    color: root.theme.alpha(root.theme.semanticForeground, 0.125)
                }
                GradientStop {
                    position: 0.11
                    color: root.theme.alpha(root.theme.semanticForeground, 0.048)
                }
                GradientStop {
                    position: 0.25
                    color: root.theme.alpha(root.accent, 0.009)
                }
                GradientStop { position: 0.58; color: "transparent" }
                GradientStop {
                    position: 1.00
                    color: root.theme.alpha(root.theme.semanticShadow, 0.25)
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            height: Math.max(2, 20 * root.dockRevealProgress)
            radius: 10
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.shellReflection }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.84
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: Math.max(4, dockShell.radius - 1)
            antialiasing: true
            color: "transparent"
            border.width: 1
            border.color: root.shellInnerRim
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 18 + 12 * root.dockRevealProgress
            anchors.rightMargin: 18 + 12 * root.dockRevealProgress
            anchors.top: parent.top
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellSpecular
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            anchors.bottom: parent.bottom
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellLowlight
            opacity: root.dockRevealProgress
        }

        // The tiny shelf is intentionally visible over tiled windows: it is a
        // reveal affordance, not a full UI overlay and reserves zero work area.
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            width: 42 + 8 * root.dockRevealProgress
            height: 2
            radius: 1
            color: root.theme.alpha(root.semanticFocus !== undefined ? root.semanticFocus : root.accent, 0.0)
            visible: false
        }

        Rectangle {
            id: retreatCue
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            width: 44
            height: 2
            radius: 1
            color: root.theme.alpha(root.theme.semanticForeground, 0.56)
            opacity: 1 - root.dockRevealProgress
        }

        Rectangle {
            id: hoverLens
            x: root.hoverLensX
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -1
            width: 70
            height: 70
            radius: 23
            color: root.theme.alpha(
                root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, 0.028),
                0.32
            )
            border.width: 1
            border.color: root.theme.alpha(root.theme.semanticForeground, 0.065)
            opacity: root.hoverLensVisible && root.dockRevealProgress > 0.82 ? 1 : 0

            Behavior on x {
                NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
            }
            Behavior on opacity {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }
        }

        Row {
            id: dockRow
            anchors.centerIn: parent
            spacing: 0
            opacity: root.dockRevealProgress
            scale: 0.965 + 0.035 * root.dockRevealProgress
            y: (parent.height - height) / 2 + 5 * (1 - root.dockRevealProgress)

            Repeater {
                model: root.dockModel.items

                delegate: Item {
                    id: appCell
                    required property var modelData
                    required property int index

                    width: 78 + (modelData.breakBefore ? 14 : 0)
                    height: 76

                    property real hoverProgress: appMouse.containsMouse ? 1 : 0
                    property real pressProgress: appMouse.pressed ? 1 : 0

                    Behavior on hoverProgress {
                        NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
                    }
                    Behavior on pressProgress {
                        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
                    }

                    Rectangle {
                        visible: modelData.breakBefore
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 1
                        height: 38
                        color: root.theme.alpha(root.theme.semanticForeground, 0.09)
                    }

                    Item {
                        id: appTarget
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 78
                        height: 76

                        Rectangle {
                            id: focusMaterial
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -2
                            width: 68
                            height: 68
                            radius: 23
                            antialiasing: true
                            color: root.theme.alpha(
                                root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, 0.070),
                                0.30
                            )
                            border.width: 1
                            border.color: root.theme.alpha(root.accent, 0.105)
                            opacity: modelData.focused ? 1 : 0

                            Behavior on opacity {
                                NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
                            }
                        }

                        Item {
                            id: iconLift
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 9 - appCell.hoverProgress * 3 + appCell.pressProgress * 1.5
                            width: 52
                            height: 52
                            scale: 1 + appCell.hoverProgress * 0.026 - appCell.pressProgress * 0.045

                            MahoDockAppIcon {
                                anchors.fill: parent
                                name: String(modelData.name || "")
                                entryId: String(modelData.id || "")
                                icon: String(modelData.icon || "")
                                iconPath: String(modelData.iconPath || "")
                            }
                        }

                        Rectangle {
                            id: runningShelf
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 4
                            width: modelData.focused ? 30
                                : modelData.running ? (modelData.windowCount > 1 ? 13 : 8)
                                : modelData.launching ? 9 : 0
                            height: modelData.focused ? 3 : 2
                            radius: 2
                            antialiasing: true
                            color: modelData.focused
                                ? root.theme.alpha(root.accent, 0.90)
                                : root.theme.alpha(root.theme.semanticForeground, modelData.onOtherWorkspace ? 0.32 : 0.60)
                            opacity: modelData.running || modelData.focused ? 1 : (modelData.launching ? 0.72 : 0)

                            Behavior on width {
                                NumberAnimation { duration: 210; easing.type: Easing.OutCubic }
                            }
                            Behavior on color {
                                ColorAnimation { duration: 200; easing.type: Easing.OutCubic }
                            }
                            Behavior on opacity {
                                NumberAnimation { duration: 170; easing.type: Easing.OutCubic }
                            }
                        }

                        Rectangle {
                            visible: modelData.running && modelData.windowCount > 1
                            anchors.left: runningShelf.right
                            anchors.leftMargin: 3
                            anchors.verticalCenter: runningShelf.verticalCenter
                            width: 3
                            height: 3
                            radius: 2
                            antialiasing: true
                            color: root.theme.alpha(
                                modelData.focused ? root.accent : root.theme.semanticForeground,
                                modelData.onOtherWorkspace ? 0.30 : 0.52
                            )
                        }

                        Rectangle {
                            id: launchPulse
                            visible: modelData.launching && !modelData.running
                            anchors.centerIn: runningShelf
                            width: 10
                            height: 2
                            radius: 1
                            color: root.theme.alpha(root.accent, 0.78)
                            opacity: 0.74

                            SequentialAnimation on opacity {
                                running: launchPulse.visible
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.28; duration: 520; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 0.82; duration: 520; easing.type: Easing.InOutSine }
                            }
                        }

                        MouseArea {
                            id: appMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                            cursorShape: Qt.PointingHandCursor
                            enabled: root.dockRevealProgress > 0.82
                            onEntered: {
                                root.showHoverLens(appTarget)
                                root.armPreview(modelData)
                            }
                            onExited: {
                                root.hideHoverLensSoon()
                                root.leaveDockItem()
                            }
                            onClicked: function(mouse) {
                                root.activateDockItem(modelData, mouse.button === Qt.MiddleButton)
                            }
                        }
                    }
                }
            }
        }

        HoverHandler {
            id: dockSurfaceHover
            cursorShape: root.dockRevealProgress < 0.82 ? Qt.PointingHandCursor : Qt.ArrowCursor
            onHoveredChanged: {
                if (!hovered && !root.dockHovering)
                    root.hideHoverLensSoon()
            }
        }
    }
}
