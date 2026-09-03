import QtQuick
import Quickshell
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
        bottom: 42
    }

    // Keep the layer-surface geometry stable while the material morphs inside
    // it. Resizing the Wayland surface during hover created the cheap, blocky
    // motion seen in the first native M1 render.
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
        theme.mix(theme.semanticSurfaceElevated, theme.semanticShadow, brightBackdrop ? 0.30 : 0.38)
    readonly property color shellMaterial:
        theme.mix(smokedNeutral, accent, 0.012)
    readonly property color shellFill:
        theme.alpha(shellMaterial, brightBackdrop ? 0.66 : 0.56)
    readonly property color shellFillRaised:
        theme.alpha(theme.mix(shellMaterial, theme.semanticSurfaceElevated, 0.14), brightBackdrop ? 0.72 : 0.61)
    readonly property color shellRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.20 : 0.15)
    readonly property color shellInnerRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.090 : 0.060)
    readonly property color shellSpecular:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.16 : 0.105)
    readonly property color shellLowlight:
        theme.alpha(theme.semanticShadow, brightBackdrop ? 0.12 : 0.20)

    readonly property int dockHeight: 86
    readonly property int previewHeight: 220
    readonly property int previewWidth: 694
    readonly property int restingDockWidth: Math.max(300, dockRow.implicitWidth + 38)
    readonly property var previewWindows:
        previewItem && Array.isArray(previewItem.windows)
            ? previewItem.windows.slice(0, 3)
            : []

    property var hoverCandidate: null
    property var previewItem: null
    property bool previewOpen: false
    property bool dockHovering: false
    property real previewProgress: previewOpen ? 1 : 0

    Behavior on previewProgress {
        NumberAnimation {
            duration: 360
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

    Timer {
        id: hoverIntent
        interval: 620
        repeat: false
        onTriggered: root.openPreview(root.hoverCandidate)
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

    // Resting input is strictly the compact shelf. While the preview is open,
    // input expands only to the visible preview+dock material envelope.
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
                    color: root.theme.alpha(root.theme.semanticForeground, 0.075)
                }
                GradientStop {
                    position: 0.20
                    color: root.theme.alpha(root.accent, 0.014)
                }
                GradientStop { position: 0.56; color: "transparent" }
                GradientStop {
                    position: 1.00
                    color: root.theme.alpha(root.theme.semanticShadow, 0.15)
                }
            }
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
            anchors.top: parent.top
            anchors.leftMargin: 32
            anchors.rightMargin: 32
            height: 1
            radius: 1
            color: root.shellSpecular
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
                        active: root.previewOpen && root.previewProgress > 0.72
                        onActivated: {
                            root.closePreview()
                            if (root.previewItem)
                                root.dockModel.activateItem(root.previewItem, false)
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
                        root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, 0.025),
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
        id: dockShell
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: root.restingDockWidth
        height: root.dockHeight
        radius: 32
        antialiasing: true
        color: root.previewOpen
            ? root.theme.alpha(root.shellMaterial, root.brightBackdrop ? 0.70 : 0.60)
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
                    color: root.theme.alpha(root.theme.semanticForeground, 0.082)
                }
                GradientStop {
                    position: 0.22
                    color: root.theme.alpha(root.accent, 0.012)
                }
                GradientStop { position: 0.58; color: "transparent" }
                GradientStop {
                    position: 1.00
                    color: root.theme.alpha(root.theme.semanticShadow, 0.18)
                }
            }
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: dockShell.radius - 1
            antialiasing: true
            color: "transparent"
            border.width: 1
            border.color: root.shellInnerRim
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 30
            anchors.rightMargin: 30
            anchors.top: parent.top
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellSpecular
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 34
            anchors.rightMargin: 34
            anchors.bottom: parent.bottom
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellLowlight
        }

        Row {
            id: dockRow
            anchors.centerIn: parent
            spacing: 0

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
                        color: root.theme.alpha(root.theme.semanticForeground, 0.08)
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
                            width: 66
                            height: 66
                            radius: 22
                            antialiasing: true
                            color: root.theme.alpha(
                                root.theme.mix(
                                    root.theme.semanticSurfaceElevated,
                                    root.accent,
                                    modelData.focused ? 0.070 : 0.025
                                ),
                                modelData.focused
                                    ? 0.28
                                    : (0.10 + appCell.hoverProgress * 0.13)
                            )
                            border.width: 1
                            border.color: root.theme.alpha(
                                modelData.focused ? root.accent : root.theme.semanticForeground,
                                modelData.focused ? 0.095 : 0.030 + appCell.hoverProgress * 0.035
                            )
                            opacity: modelData.focused ? 1 : appCell.hoverProgress

                            Behavior on color {
                                ColorAnimation { duration: 210; easing.type: Easing.OutCubic }
                            }
                            Behavior on border.color {
                                ColorAnimation { duration: 210; easing.type: Easing.OutCubic }
                            }
                        }

                        Item {
                            id: iconLift
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 10 - appCell.hoverProgress * 3 + appCell.pressProgress * 1.5
                            width: 50
                            height: 50
                            scale: 1 + appCell.hoverProgress * 0.030 - appCell.pressProgress * 0.045

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
                            anchors.bottomMargin: 5
                            width: modelData.focused ? 30
                                : modelData.running ? (modelData.windowCount > 1 ? 13 : 8)
                                : modelData.launching ? 9 : 0
                            height: modelData.focused ? 3 : 2
                            radius: 2
                            antialiasing: true
                            color: modelData.focused
                                ? root.theme.alpha(root.accent, 0.90)
                                : root.theme.alpha(root.theme.semanticForeground, modelData.onOtherWorkspace ? 0.32 : 0.58)
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
                            onEntered: root.armPreview(modelData)
                            onExited: root.leaveDockItem()
                            onClicked: function(mouse) {
                                root.activateDockItem(modelData, mouse.button === Qt.MiddleButton)
                            }
                        }
                    }
                }
            }
        }
    }
}
