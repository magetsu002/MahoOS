import QtQuick

Item {
    id: edge

    property var theme
    property var audio
    property var brightness
    property var system
    property var battery
    property var workspaceIds: []
    property int activeWorkspace: 0
    property bool workspaceFlash: false
    property int workspaceEventSerial: 0
    property date now: new Date()
    property bool hovered: hitArea.containsMouse
    property real workspacePulse: 1.0

    readonly property string mode:
        brightness && brightness.overlayOpen ? "brightness"
        : audio && audio.overlayOpen ? "volume"
        : workspaceFlash ? "workspace"
        : "idle"

    signal openRequested()

    function networkGlyph() {
        if (system && system.networkKind === "wifi") return "󰖩"
        if (system && system.networkKind === "ethernet") return "󰈀"
        return "󰖪"
    }

    function batteryGlyph() {
        if (battery && battery.charging) return "󰂄"
        const value = battery ? battery.percentage : 100
        if (value >= 90) return "󰁹"
        if (value >= 70) return "󰂀"
        if (value >= 50) return "󰁾"
        if (value >= 30) return "󰁼"
        return "󰁺"
    }

    function volumeGlyph() {
        if (audio && audio.muted) return "󰖁"
        const value = audio ? audio.volume : 0
        if (value < 30) return ""
        if (value < 70) return ""
        return ""
    }

    onWorkspaceEventSerialChanged: {
        if (workspaceEventSerial > 0)
            workspacePulseAnimation.restart()
    }

    SequentialAnimation {
        id: workspacePulseAnimation

        NumberAnimation {
            target: edge
            property: "workspacePulse"
            from: 0.82
            to: 1.12
            duration: 90
            easing.type: Easing.OutCubic
        }

        NumberAnimation {
            target: edge
            property: "workspacePulse"
            to: 1.0
            duration: 130
            easing.type: Easing.OutCubic
        }
    }

    // Same pointer ownership as the horizontal Maho Edge surface.
    MouseArea {
        id: hitArea
        anchors.fill: parent
        enabled: edge.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.MiddleButton

        onClicked: function(mouse) {
            if (mouse.button === Qt.MiddleButton && edge.audio)
                edge.audio.toggleMute()
        }

        onWheel: function(wheel) {
            if (!edge.audio)
                return

            const direction = wheel.angleDelta.y > 0 ? 1 : -1
            edge.audio.setVolume(edge.audio.volume + direction * 5)
            wheel.accepted = true
        }
    }

    TapHandler {
        enabled: edge.enabled
        acceptedButtons: Qt.LeftButton
        onTapped: edge.openRequested()
    }

    Item {
        anchors.fill: parent
        opacity: edge.mode === "idle" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Text {
            anchors.top: parent.top
            anchors.topMargin: 16
            anchors.horizontalCenter: parent.horizontalCenter
            text: edge.networkGlyph()
            color: edge.theme
                ? (edge.system && edge.system.networkKind === "none"
                    ? edge.theme.error : edge.theme.muted)
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            Behavior on color { ColorAnimation { duration: 360 } }
        }

        Column {
            anchors.centerIn: parent
            spacing: -1

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(edge.now, "HH")
                color: edge.theme ? edge.theme.foreground : "white"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 12
                font.weight: Font.DemiBold
                Behavior on color { ColorAnimation { duration: 360 } }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 12
                height: 1
                color: edge.theme ? edge.theme.alpha(edge.theme.primary, 0.55) : "white"
                Behavior on color { ColorAnimation { duration: 360 } }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(edge.now, "mm")
                color: edge.theme ? edge.theme.foreground : "white"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 12
                font.weight: Font.DemiBold
                Behavior on color { ColorAnimation { duration: 360 } }
            }
        }

        Text {
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 16
            anchors.horizontalCenter: parent.horizontalCenter
            visible: edge.battery ? edge.battery.available : false
            text: edge.batteryGlyph()
            color: edge.theme
                ? (edge.battery && edge.battery.percentage <= 15
                    ? edge.theme.error
                    : (edge.battery && edge.battery.charging
                        ? edge.theme.primary : edge.theme.muted))
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            Behavior on color { ColorAnimation { duration: 360 } }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 4
        scale: edge.workspacePulse
        opacity: edge.mode === "workspace" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 110 } }

        Repeater {
            model: edge.workspaceIds
            delegate: Rectangle {
                required property var modelData
                width: 5
                height: modelData === edge.activeWorkspace ? 18 : 5
                radius: 3
                color: edge.theme
                    ? (modelData === edge.activeWorkspace
                        ? edge.theme.primary
                        : edge.theme.alpha(edge.theme.muted, 0.32))
                    : "white"

                Behavior on height {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
                Behavior on color { ColorAnimation { duration: 180 } }
            }
        }
    }

    Column {
        id: osdView
        anchors.top: parent.top
        anchors.topMargin: 15
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 15
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 7
        opacity: (edge.mode === "volume" || edge.mode === "brightness") ? 1 : 0
        visible: opacity > 0.01

        readonly property bool isVolume: edge.mode === "volume"
        readonly property int value: isVolume
            ? (edge.audio ? edge.audio.volume : 0)
            : (edge.brightness ? Math.max(0, edge.brightness.value) : 0)

        Behavior on opacity { NumberAnimation { duration: 130 } }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: osdView.isVolume ? edge.volumeGlyph() : "󰃠"
            color: edge.theme
                ? (osdView.isVolume ? edge.theme.primary : edge.theme.tertiary)
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            Behavior on color { ColorAnimation { duration: 320 } }
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 5
            height: Math.max(72, parent.height - 67)
            radius: 3
            color: edge.theme ? edge.theme.alpha(edge.theme.muted, 0.16) : "#33333a"

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: parent.height * Math.min(100, osdView.value) / 100
                radius: parent.radius
                color: edge.theme
                    ? (osdView.isVolume ? edge.theme.primary : edge.theme.tertiary)
                    : "white"
                Behavior on height { NumberAnimation { duration: 80; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 320 } }
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: osdView.value + "%"
            color: edge.theme ? edge.theme.foreground : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 8
            font.weight: Font.DemiBold
            Behavior on color { ColorAnimation { duration: 320 } }
        }
    }
}
