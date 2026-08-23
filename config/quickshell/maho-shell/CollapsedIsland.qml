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

    // Keep hover/wheel/middle-click on a MouseArea, but deliberately do not
    // accept the left button here. Left-button ownership stays with the
    // cooperative TapHandler + parent DragHandler pair, so a click can become
    // a drag reliably instead of racing a MouseArea grab.
    MouseArea {
        id: hitArea
        anchors.fill: parent
        enabled: collapsed.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.MiddleButton

        onClicked: function(mouse) {
            if (mouse.button === Qt.MiddleButton && collapsed.audio)
                collapsed.audio.toggleMute()
        }

        onWheel: function(wheel) {
            if (!collapsed.audio)
                return

            const direction = wheel.angleDelta.y > 0 ? 1 : -1
            collapsed.audio.setVolume(collapsed.audio.volume + direction * 5)
            wheel.accepted = true
        }
    }

    TapHandler {
        enabled: collapsed.enabled
        acceptedButtons: Qt.LeftButton
        onTapped: collapsed.openRequested()
    }

    Item {
        id: idleView
        anchors.fill: parent
        opacity: collapsed.mode === "idle" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: collapsed.networkGlyph()
            color: collapsed.theme
                ? (collapsed.system && collapsed.system.networkKind === "none"
                    ? collapsed.theme.error : collapsed.theme.muted)
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            Behavior on color { ColorAnimation { duration: 360 } }
        }

        Text {
            anchors.centerIn: parent
            text: Qt.formatDateTime(collapsed.now, "HH:mm")
            color: collapsed.theme ? collapsed.theme.foreground : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 0.5
            Behavior on color { ColorAnimation { duration: 360 } }
        }

        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
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

    Row {
        id: workspaceView
        anchors.centerIn: parent
        spacing: 4
        opacity: collapsed.mode === "workspace" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Repeater {
            model: collapsed.workspaceIds
            delegate: Rectangle {
                required property var modelData
                width: modelData === collapsed.activeWorkspace ? 18 : 5
                height: 5
                radius: 3
                color: collapsed.theme
                    ? (modelData === collapsed.activeWorkspace
                        ? collapsed.theme.primary
                        : collapsed.theme.alpha(collapsed.theme.muted, 0.32))
                    : "white"

                Behavior on width {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
                Behavior on color { ColorAnimation { duration: 260 } }
            }
        }
    }

    Row {
        id: osdView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 9
        opacity: (collapsed.mode === "volume" || collapsed.mode === "brightness") ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 130 } }

        readonly property bool isVolume: collapsed.mode === "volume"
        readonly property int value: isVolume
            ? (collapsed.audio ? collapsed.audio.volume : 0)
            : (collapsed.brightness ? Math.max(0, collapsed.brightness.value) : 0)

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: osdView.isVolume ? collapsed.volumeGlyph() : "󰃠"
            color: collapsed.theme
                ? (osdView.isVolume ? collapsed.theme.primary : collapsed.theme.tertiary)
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 14
            Behavior on color { ColorAnimation { duration: 320 } }
        }

        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: Math.max(70, parent.width - 77)
            height: 5
            radius: 3
            color: collapsed.theme ? collapsed.theme.alpha(collapsed.theme.muted, 0.16) : "#33333a"

            Rectangle {
                width: parent.width * Math.min(100, osdView.value) / 100
                height: parent.height
                radius: parent.radius
                color: collapsed.theme
                    ? (osdView.isVolume ? collapsed.theme.primary : collapsed.theme.tertiary)
                    : "white"
                Behavior on width { NumberAnimation { duration: 80; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 320 } }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            horizontalAlignment: Text.AlignRight
            text: osdView.value + "%"
            color: collapsed.theme ? collapsed.theme.foreground : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 10
            font.weight: Font.DemiBold
            Behavior on color { ColorAnimation { duration: 320 } }
        }
    }
}
