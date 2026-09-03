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
        bottom: 2
    }

    // Keep layer-shell geometry stable. All reveal/preview motion stays inside
    // this carrier so Hyprland never has to chase a resizing surface.
    implicitWidth: 720
    implicitHeight: 438
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

    readonly property real darkGlassLift: brightBackdrop ? 0.020 : 0.085
    readonly property color smokedNeutral:
        theme.mix(theme.semanticSurfaceElevated, theme.semanticShadow, brightBackdrop ? 0.40 : 0.34)
    readonly property color liftedNeutral:
        theme.mix(smokedNeutral, theme.semanticForeground, darkGlassLift)
    readonly property color shellMaterial:
        theme.mix(liftedNeutral, accent, 0.005)
    readonly property color shellFill:
        theme.alpha(shellMaterial, brightBackdrop ? 0.56 : 0.50)
    readonly property color shellFillRaised:
        theme.alpha(theme.mix(shellMaterial, theme.semanticSurfaceElevated, 0.13), brightBackdrop ? 0.67 : 0.58)
    readonly property color shellRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.29 : 0.26)
    readonly property color shellOuterRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.090 : 0.078)
    readonly property color shellInnerRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.12 : 0.11)
    readonly property color shellSpecular:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.23 : 0.22)
    readonly property color shellReflection:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.095 : 0.105)
    readonly property color shellLowlight:
        theme.alpha(theme.semanticShadow, brightBackdrop ? 0.17 : 0.22)
    readonly property color shellWell:
        theme.alpha(theme.mix(theme.semanticSurfaceElevated, theme.semanticForeground, brightBackdrop ? 0.01 : 0.045), brightBackdrop ? 0.16 : 0.18)

    readonly property int dockHeight: 84
    readonly property int retractedHeight: 12
    readonly property int retractedWidth: 104
    readonly property int previewHeight: 324
    readonly property int previewWidth: 694
    readonly property int restingDockWidth: Math.max(320, dockRow.implicitWidth + 46)
    readonly property var previewWindows: {
        if (!previewItem || !previewItem.windows)
            return []
        const windows = previewItem.windows
        if (windows.slice)
            return windows.slice(0, 3)
        const output = []
        const count = Math.min(3, Number(windows.length || 0))
        for (let index = 0; index < count; ++index)
            output.push(windows[index])
        return output
    }
    readonly property int previewCount: previewWindows.length
    readonly property int previewTargetWidth:
        previewCount <= 1 ? 540 : (previewCount === 2 ? 660 : previewWidth)
    readonly property int previewCardWidth:
        previewCount <= 1 ? 414 : (previewCount === 2 ? 304 : 198)
    readonly property int previewCardHeight:
        previewCount <= 1 ? 208 : (previewCount === 2 ? 170 : 138)

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
        return activeIpc.floating === false
    }

    property var hoverCandidate: null
    property var previewItem: null
    property bool previewOpen: false
    property real previewProgress: previewOpen ? 1 : 0

    property bool hoverLensVisible: false
    property real hoverLensX: 0
    property bool hoverLensFocused: false
    property string pinFeedbackText: ""

    readonly property bool pointerInsideMaterial:
        dockSurfaceHover.hovered || previewHover.hovered

    readonly property bool retreatRequested:
        activeWindowOccupiesDock
        && !pointerInsideMaterial
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
        previewDismiss.stop()

        if (!item || !item.running || !item.windows || item.windows.length === 0) {
            hoverCandidate = null
            hoverIntent.stop()
            return
        }

        hoverCandidate = item
        if (previewOpen && previewItem && String(previewItem.id) === String(item.id))
            return
        hoverIntent.restart()
    }

    function leaveDockItem() {
        hoverIntent.stop()
        if (!root.pointerInsideMaterial)
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
        hoverIntent.stop()
        if (!previewOpen)
            return
        previewOpen = false
        previewClear.restart()
    }

    function activateDockItem(item, newWindow) {
        closePreview()
        dockModel.activateItem(item, newWindow)
    }

    function togglePin(item) {
        closePreview()
        if (!item || item.temporary) {
            pinFeedbackText = "This window has no pinnable app identity"
            pinFeedbackTimer.restart()
            return
        }

        const wasPinned = Boolean(item.pinned)
        if (wasPinned)
            dockModel.unpinItem(item)
        else
            dockModel.pinItem(item)

        pinFeedbackText = (wasPinned ? "Unpinned " : "Pinned ") + String(item.name || "Application")
        pinFeedbackTimer.restart()
    }

    function showHoverLens(target, focused) {
        hoverLensClear.stop()
        if (!target)
            return
        const center = target.mapToItem(dockShell, target.width / 2, target.height / 2)
        hoverLensX = center.x - hoverLens.width / 2
        hoverLensFocused = !!focused
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
        interval: 110
        repeat: false
        onTriggered: root.hoverLensVisible = false
    }

    Timer {
        id: previewDismiss
        interval: 210
        repeat: false
        onTriggered: {
            if (!root.pointerInsideMaterial)
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

    Timer {
        id: pinFeedbackTimer
        interval: 1200
        repeat: false
        onTriggered: root.pinFeedbackText = ""
    }

    mask: Region {
        item: root.previewOpen || root.previewProgress > 0.02 ? materialBounds : dockShell
    }

    Item {
        id: materialBounds
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: root.previewWidth
        height: root.previewHeight + root.dockHeight + 10
    }

    Rectangle {
        id: pinFeedback
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: dockShell.top
        anchors.bottomMargin: 8
        width: Math.max(126, pinFeedbackLabel.implicitWidth + 28)
        height: 30
        radius: 15
        visible: root.pinFeedbackText.length > 0 && !root.previewOpen
        opacity: visible ? 1 : 0
        color: root.theme.alpha(root.shellMaterial, root.brightBackdrop ? 0.78 : 0.72)
        border.width: 1
        border.color: root.theme.alpha(root.theme.semanticForeground, 0.12)

        Text {
            id: pinFeedbackLabel
            anchors.centerIn: parent
            text: root.pinFeedbackText
            color: root.theme.semanticForeground
            font.pixelSize: 10
            font.weight: Font.Medium
        }

        Behavior on opacity {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        id: previewDepth
        anchors.horizontalCenter: previewShell.horizontalCenter
        anchors.top: previewShell.top
        anchors.topMargin: 4
        width: previewShell.width + 5
        height: previewShell.height + 4
        radius: previewShell.radius + 3
        color: root.theme.alpha(root.theme.semanticShadow, brightBackdrop ? 0.22 : 0.18)
        opacity: root.previewProgress * 0.72
    }

    Rectangle {
        id: previewShell
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: dockShell.top
        anchors.bottomMargin: 8
        width: root.restingDockWidth
            + (root.previewTargetWidth - root.restingDockWidth) * root.previewProgress
        height: root.previewHeight * root.previewProgress
        radius: 28
        antialiasing: true
        color: root.shellFillRaised
        border.width: 1
        border.color: root.shellRim
        clip: true
        opacity: root.previewProgress
        transformOrigin: Item.Bottom
        scale: 0.985 + 0.015 * root.previewProgress

        Rectangle {
            anchors.fill: parent
            radius: previewShell.radius
            antialiasing: true
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.00; color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.10 : 0.13) }
                GradientStop { position: 0.14; color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.030 : 0.046) }
                GradientStop { position: 0.34; color: root.theme.alpha(root.accent, 0.006) }
                GradientStop { position: 0.66; color: "transparent" }
                GradientStop { position: 1.00; color: root.theme.alpha(root.theme.semanticShadow, brightBackdrop ? 0.18 : 0.14) }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            height: 21
            radius: 10
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.shellReflection }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.82
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

        Item {
            id: previewContent
            anchors.fill: parent
            opacity: Math.max(0, Math.min(1, (root.previewProgress - 0.16) / 0.84))
            y: 10 * (1 - root.previewProgress)

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

            Item {
                id: previewStage
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: previewHeader.bottom
                anchors.bottom: previewActions.top
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                anchors.topMargin: 13
                anchors.bottomMargin: 12

                Row {
                    id: previewRow
                    anchors.centerIn: parent
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
                            cardWidth: root.previewCardWidth
                            cardHeight: root.previewCardHeight
                            active: root.previewOpen && root.previewProgress > 0.62
                            onActivated: function(windowData) {
                                root.closePreview()
                                root.dockModel.focusWindow(windowData)
                            }
                        }
                    }
                }
            }

            Row {
                id: previewActions
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 16
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 14

                Rectangle {
                    id: newWindowAction
                    visible: root.previewItem && !root.previewItem.temporary
                    width: 128
                    height: 30
                    radius: 15
                    color: root.theme.alpha(root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, 0.015), newWindowHover.hovered ? 0.54 : 0.38)
                    border.width: 1
                    border.color: root.theme.alpha(newWindowHover.hovered ? root.accent : root.theme.semanticForeground, newWindowHover.hovered ? 0.17 : 0.060)

                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on border.color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }

                    Text {
                        anchors.centerIn: parent
                        text: "New Window"
                        color: root.theme.semanticForeground
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }

                    HoverHandler { id: newWindowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        acceptedButtons: Qt.LeftButton
                        onTapped: {
                            if (root.previewItem)
                                root.activateDockItem(root.previewItem, true)
                        }
                    }
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.previewItem
                        ? String(root.previewItem.windowCount || 0) + (Number(root.previewItem.windowCount || 0) === 1 ? " window" : " windows")
                        : ""
                    color: root.theme.semanticForegroundMuted
                    opacity: 0.56
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }
            }
        }

        HoverHandler {
            id: previewHover
            onHoveredChanged: {
                if (hovered)
                    previewDismiss.stop()
                else if (!dockSurfaceHover.hovered)
                    previewDismiss.restart()
            }
        }
    }

    Rectangle {
        id: dockHalo
        anchors.horizontalCenter: dockShell.horizontalCenter
        anchors.verticalCenter: dockShell.verticalCenter
        width: dockShell.width + 10
        height: dockShell.height + 10
        radius: dockShell.radius + 5
        color: "transparent"
        border.width: 1
        border.color: root.shellOuterRim
        opacity: 0.28 + 0.40 * root.dockRevealProgress
    }

    Rectangle {
        id: dockDepth
        anchors.horizontalCenter: dockShell.horizontalCenter
        anchors.bottom: dockShell.bottom
        anchors.bottomMargin: -3
        width: dockShell.width + 6
        height: dockShell.height + 5
        radius: dockShell.radius + 3
        color: root.theme.alpha(root.theme.semanticShadow, brightBackdrop ? 0.24 : 0.17)
        opacity: 0.48 + 0.30 * root.dockRevealProgress
    }

    Rectangle {
        id: dockShell
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        width: root.retractedWidth + (root.restingDockWidth - root.retractedWidth) * root.dockRevealProgress
        height: root.retractedHeight + (root.dockHeight - root.retractedHeight) * root.dockRevealProgress
        radius: 6 + 25 * root.dockRevealProgress
        antialiasing: true
        color: root.previewOpen
            ? root.theme.alpha(root.shellMaterial, root.brightBackdrop ? 0.60 : 0.53)
            : root.shellFill
        border.width: 1
        border.color: root.shellRim
        clip: true

        Behavior on color { ColorAnimation { duration: 300; easing.type: Easing.OutCubic } }

        Rectangle {
            anchors.fill: parent
            radius: dockShell.radius
            antialiasing: true
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.00; color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.125 : 0.160) }
                GradientStop { position: 0.11; color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.044 : 0.065) }
                GradientStop { position: 0.30; color: root.theme.alpha(root.accent, 0.005) }
                GradientStop { position: 0.60; color: "transparent" }
                GradientStop { position: 1.00; color: root.theme.alpha(root.theme.semanticShadow, brightBackdrop ? 0.22 : 0.15) }
            }
        }

        Rectangle {
            id: dockInnerWell
            anchors.fill: parent
            anchors.margins: 6
            radius: Math.max(3, dockShell.radius - 6)
            color: root.shellWell
            border.width: 1
            border.color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.038 : 0.055)
            opacity: root.dockRevealProgress
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 11
            anchors.rightMargin: 11
            height: Math.max(2, 26 * root.dockRevealProgress)
            radius: 13
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: root.shellReflection }
                GradientStop { position: 0.42; color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.016 : 0.030) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.90
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
            anchors.leftMargin: 16 + 13 * root.dockRevealProgress
            anchors.rightMargin: 16 + 13 * root.dockRevealProgress
            anchors.top: parent.top
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellSpecular
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 26
            anchors.rightMargin: 26
            anchors.bottom: parent.bottom
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellLowlight
            opacity: root.dockRevealProgress
        }

        Rectangle {
            id: retreatCue
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            width: 48
            height: 2
            radius: 1
            color: root.theme.alpha(root.theme.semanticForeground, brightBackdrop ? 0.56 : 0.72)
            opacity: 1 - root.dockRevealProgress
        }

        Rectangle {
            id: hoverLens
            x: root.hoverLensX
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -1
            width: 66
            height: 66
            radius: 22
            color: root.theme.alpha(
                root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, root.hoverLensFocused ? 0.020 : 0.012),
                root.hoverLensFocused ? 0.10 : 0.16
            )
            border.width: 1
            border.color: root.theme.alpha(root.theme.semanticForeground, root.hoverLensFocused ? 0.040 : 0.060)
            opacity: root.hoverLensVisible && root.dockRevealProgress > 0.82 ? 1 : 0

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                height: 1
                color: root.theme.alpha(root.theme.semanticForeground, 0.060)
            }

            Behavior on x { NumberAnimation { duration: 185; easing.type: Easing.OutCubic } }
            Behavior on opacity { NumberAnimation { duration: 145; easing.type: Easing.OutCubic } }
        }

        Row {
            id: dockRow
            anchors.centerIn: parent
            spacing: 0
            opacity: root.dockRevealProgress
            scale: 0.975 + 0.025 * root.dockRevealProgress
            y: (parent.height - height) / 2 + 3 * (1 - root.dockRevealProgress)

            Repeater {
                model: root.dockModel.items

                delegate: Item {
                    id: appCell
                    required property var modelData
                    required property int index

                    width: 80 + (modelData.breakBefore ? 14 : 0)
                    height: 74

                    property real hoverProgress: appMouse.containsMouse ? 1 : 0
                    property real pressProgress: appMouse.pressed ? 1 : 0

                    Behavior on hoverProgress { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                    Behavior on pressProgress { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }

                    Rectangle {
                        visible: modelData.breakBefore
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        width: 1
                        height: 36
                        color: root.theme.alpha(root.theme.semanticForeground, 0.080)
                    }

                    Item {
                        id: appTarget
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 80
                        height: 74

                        Rectangle {
                            id: focusMaterial
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -1
                            width: 68
                            height: 68
                            radius: 23
                            antialiasing: true
                            color: root.theme.alpha(root.theme.mix(root.theme.semanticSurfaceElevated, root.accent, 0.045), brightBackdrop ? 0.22 : 0.19)
                            border.width: 1
                            border.color: root.theme.alpha(root.accent, 0.095)
                            opacity: modelData.focused ? 1 : 0

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.leftMargin: 13
                                anchors.rightMargin: 13
                                height: 1
                                color: root.theme.alpha(root.theme.semanticForeground, 0.075)
                            }

                            Behavior on opacity { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
                        }

                        Item {
                            id: iconLift
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 8 - appCell.hoverProgress * 1.5 + appCell.pressProgress * 1.2
                            width: 53
                            height: 53
                            scale: 1 + appCell.hoverProgress * 0.016 - appCell.pressProgress * 0.040

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
                            anchors.bottomMargin: 3
                            width: modelData.focused ? 30
                                : modelData.running ? (modelData.windowCount > 1 ? 13 : 8)
                                : modelData.launching ? 9 : 0
                            height: modelData.focused ? 3 : 2
                            radius: 2
                            antialiasing: true
                            color: modelData.focused
                                ? root.theme.alpha(root.accent, 0.90)
                                : root.theme.alpha(root.theme.semanticForeground, modelData.onOtherWorkspace ? 0.34 : 0.62)
                            opacity: modelData.running || modelData.focused ? 1 : (modelData.launching ? 0.72 : 0)

                            Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                            Behavior on color { ColorAnimation { duration: 190; easing.type: Easing.OutCubic } }
                            Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                        }

                        Rectangle {
                            visible: modelData.running && modelData.windowCount > 1
                            anchors.left: runningShelf.right
                            anchors.leftMargin: 3
                            anchors.verticalCenter: runningShelf.verticalCenter
                            width: 3
                            height: 3
                            radius: 2
                            color: root.theme.alpha(modelData.focused ? root.accent : root.theme.semanticForeground, modelData.onOtherWorkspace ? 0.30 : 0.50)
                        }

                        Rectangle {
                            id: launchPulse
                            visible: modelData.launching && !modelData.running
                            anchors.centerIn: runningShelf
                            width: 10
                            height: 2
                            radius: 1
                            color: root.theme.alpha(root.accent, 0.76)
                            opacity: 0.72

                            SequentialAnimation on opacity {
                                running: launchPulse.visible
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.28; duration: 520; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 0.80; duration: 520; easing.type: Easing.InOutSine }
                            }
                        }

                        MouseArea {
                            id: appMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                            cursorShape: Qt.PointingHandCursor
                            enabled: root.dockRevealProgress > 0.82
                            onEntered: {
                                root.showHoverLens(appTarget, modelData.focused)
                                root.armPreview(modelData)
                            }
                            onExited: {
                                root.hideHoverLensSoon()
                                root.leaveDockItem()
                            }
                            onClicked: function(mouse) {
                                if (mouse.button === Qt.RightButton) {
                                    root.togglePin(modelData)
                                    return
                                }
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
                if (hovered) {
                    previewDismiss.stop()
                } else {
                    root.hideHoverLensSoon()
                    if (!previewHover.hovered)
                        previewDismiss.restart()
                }
            }
        }
    }
}
