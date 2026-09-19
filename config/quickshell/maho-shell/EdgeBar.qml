import QtQuick
import Quickshell

Item {
    id: edge

    property var theme
    property var audio
    property var brightness
    property var system
    property var battery
    property var updateState
    property var workspaceIds: []
    property int activeWorkspace: 0
    property bool workspaceFlash: false
    property int workspaceEventSerial: 0
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

    function openMahoLink() {
        const override = Quickshell.env("MAHO_LINK_LAUNCHER")
        const launcher = override !== ""
            ? override
            : Quickshell.env("HOME") + "/.local/bin/maho-link"
        Quickshell.execDetached(["bash", launcher])
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

    // Hover, wheel and middle click live here. Left-click ownership remains
    // cooperative with the parent drag handler so Maho Edge can still be moved.
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
        onTapped: {
            // The resting Wi-Fi glyph owns only its compact left hit target.
            // Every other click keeps the accepted Edge expansion behavior.
            if (edge.mode === "idle" && point.position.x <= 32)
                edge.openMahoLink()
            else
                edge.openRequested()
        }
    }

    Item {
        id: idleView
        anchors.fill: parent
        opacity: edge.mode === "idle" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 150 } }

        Text {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            text: edge.networkGlyph()
            color: edge.theme
                ? (edge.system && edge.system.networkKind === "none"
                    ? edge.theme.error : edge.theme.muted)
                : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            Behavior on color { ColorAnimation { duration: 360 } }
        }

        Text {
            anchors.centerIn: parent
            text: Qt.formatDateTime(edge.now, "HH:mm")
            color: edge.theme ? edge.theme.foreground : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            font.weight: Font.DemiBold
            font.letterSpacing: 0.5
            Behavior on color { ColorAnimation { duration: 360 } }
        }

        Text {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
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

        Text {
            anchors.right: parent.right
            anchors.rightMargin: edge.battery && edge.battery.available ? 22 : 0
            anchors.verticalCenter: parent.verticalCenter
            visible: edge.updateState && (edge.updateState.activationPending || edge.updateState.attentionRequired)
            text: edge.updateState && edge.updateState.attentionRequired ? "!" : "•"
            color: edge.theme
                ? (edge.updateState && edge.updateState.attentionRequired ? edge.theme.error : edge.theme.primary)
                : "white"
            font.pixelSize: 12
            font.weight: Font.Bold
        }
    }

    WorkspaceRail {
        id: workspaceView
        anchors.centerIn: parent
        theme: edge.theme
        activeWorkspace: edge.activeWorkspace
        vertical: false
        opacity: edge.mode === "workspace" ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 110 } }
    }

    Row {
        id: osdView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 9
        opacity: (edge.mode === "volume" || edge.mode === "brightness") ? 1 : 0
        visible: opacity > 0.01

        Behavior on opacity { NumberAnimation { duration: 130 } }

        readonly property bool isVolume: edge.mode === "volume"
        readonly property int value: isVolume
            ? (edge.audio ? edge.audio.volume : 0)
            : (edge.brightness ? Math.max(0, edge.brightness.value) : 0)

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: osdView.isVolume ? edge.volumeGlyph() : "󰃠"
            color: edge.theme
                ? (osdView.isVolume ? edge.theme.primary : edge.theme.tertiary)
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
            color: edge.theme ? edge.theme.alpha(edge.theme.muted, 0.16) : "#33333a"

            Rectangle {
                width: parent.width * Math.min(100, osdView.value) / 100
                height: parent.height
                radius: Math.min(parent.radius, width / 2)
                antialiasing: true
                color: edge.theme
                    ? (osdView.isVolume ? edge.theme.primary : edge.theme.tertiary)
                    : "white"
                Behavior on width { SmoothedAnimation { duration: 110; velocity: 760; easing.type: Easing.OutCubic } }
                Behavior on color { ColorAnimation { duration: 320 } }
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            horizontalAlignment: Text.AlignRight
            text: osdView.value + "%"
            color: edge.theme ? edge.theme.foreground : "white"
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 10
            font.weight: Font.DemiBold
            Behavior on color { ColorAnimation { duration: 320 } }
        }
    }
}
