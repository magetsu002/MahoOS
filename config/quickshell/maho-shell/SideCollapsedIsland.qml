import QtQuick

Item {
    id: collapsed

    property var theme
    property var audio
    property var brightness
    property var system
    property var battery
    property var workspaceIds: []
    property int activeWorkspace: 0
    property bool workspaceFlash: false
    property date now: new Date()
    property bool hovered: hitArea.containsMouse

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

    MouseArea {
        id: hitArea
        anchors.fill: parent
        enabled: collapsed.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton | Qt.MiddleButton

        onClicked: function(mouse) {
            if (mouse.button === Qt.MiddleButton) {
                if (collapsed.audio)
                    collapsed.audio.toggleMute()
                return
            }

            collapsed.openRequested()
        }

        onWheel: function(wheel) {
            if (!collapsed.audio)
                return

            const direction = wheel.angleDelta.y > 0 ? 1 : -1
            collapsed.audio.setVolume(collapsed.audio.volume + direction * 5)
            wheel.accepted = true
        }
    }

    Item {
        anchors.fill: parent
        opacity: collapsed.mode === "idle" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Text {
            anchors.top: parent.top
            anchors.topMargin: 16
            anchors.horizontalCenter: parent.horizontalCenter
            text: collapsed.networkGlyph()
            color: collapsed.theme
                ? (collapsed.system && collapsed.system.networkKind === "none"
                    ? collapsed.theme.error : collapsed.theme.muted)
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
                text: Qt.formatDateTime(collapsed.now, "HH")
                color: collapsed.theme ? collapsed.theme.foreground : "white"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 12
                font.weight: Font.DemiBold
                Behavior on color { ColorAnimation { duration: 360 } }
            }

            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 12
                height: 1
                color: collapsed.theme ? collapsed.theme.alpha(collapsed.theme.primary, 0.55) : "white"
                Behavior on color { ColorAnimation { duration: 360 } }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: Qt.formatDateTime(collapsed.now, "mm")
                color: collapsed.theme ? collapsed.theme.foreground : "white"
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
            visible: collapsed.battery ? collapsed.battery.available : false
            text: collapsed.batteryGlyph()
            color: collapsed.theme
                ? (collapsed.battery && collapsed.battery.percentage <= 15
                    ? collapsed.theme.error
                    : (collapsed.battery && collapsed.battery.charging
                        ? collapsed.theme.primary : collapsed.theme.muted))
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            Behavior on color { ColorAnimation { duration: 360 } }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 4
        opacity: collapsed.mode === "workspace" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Repeater {
            model: collapsed.workspaceIds
            delegate: Rectangle {
                required property var modelData
                width: 5
                height: modelData === collapsed.activeWorkspace ? 18 : 5
                radius: 3
                color: collapsed.theme
                    ? (modelData === collapsed.activeWorkspace
                        ? collapsed.theme.primary
                        : collapsed.theme.alpha(collapsed.theme.muted, 0.32))
                    : "white"

                Behavior on height {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
                Behavior on color { ColorAnimation { duration: 260 } }
            }
        }
    }

    Column {
        id: osdView
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        topPadding: 15
        bottomPadding: 15
        spacing: 7
        opacity: (collapsed.mode === "volume" || collapsed.mode === "brightness") ? 1 : 0
        visible: opacity > 0.01

        readonly property bool isVolume: collapsed.mode === "volume"
        readonly property int value: isVolume
            ? (collapsed.audio ? collapsed.audio.volume : 0)
            : (collapsed.brightness ? Math.max(0, collapsed.brightness.value) : 0)

        Behavior on opacity { NumberAnimation { duration: 130 } }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: osdView.isVolume ? collapsed.volumeGlyph() : "󰃠"
            color: collapsed.theme
                ? (osdView.isVolume ? collapsed.theme.primary : collapsed.theme.tertiary)
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
            color: collapsed.theme ? collapsed.theme.alpha(collapsed.theme.muted, 0.16) : "#33333a"

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: parent.height * Math.min(100, osdView.value) / 100
                radius: parent.radius
                color: collapsed.theme
                    ? (osdView.isVolume ? collapsed.theme.primary : collapsed.theme.tertiary)
                    : "white"
                Behavior on height { NumberAnimation { duration: 80; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 320 } }
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: osdView.value + "%"
            color: collapsed.theme ? collapsed.theme.foreground : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 8
            font.weight: Font.DemiBold
            Behavior on color { ColorAnimation { duration: 320 } }
        }
    }
}
