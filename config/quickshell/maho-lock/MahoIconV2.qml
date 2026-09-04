import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

Item {
    id: root

    property string name: "lock"
    property real iconOpacity: 0.82
    property bool statusOpen: false
    property string statusOverride: ""

    readonly property var batteryDevice: UPower.displayDevice
    readonly property bool batteryReady:
        batteryDevice !== null && batteryDevice.ready
    readonly property real batteryFraction: {
        if (!batteryReady)
            return -1
        const raw = Number(batteryDevice.percentage)
        if (!Number.isFinite(raw))
            return -1
        return Math.max(0, Math.min(1, raw))
    }
    readonly property bool batteryCharging: batteryReady && (
        batteryDevice.state === UPowerDeviceState.Charging
        || batteryDevice.state === UPowerDeviceState.PendingCharge
    )
    readonly property bool batteryFull: batteryReady && (
        batteryDevice.state === UPowerDeviceState.FullyCharged
        || batteryFraction >= 0.995
    )

    readonly property bool statusInteractive:
        name === "wifi" || name === "battery" || name === "keyboard"

    readonly property string resolvedName: {
        if (name !== "battery")
            return name
        if (batteryCharging)
            return "battery-charging"
        if (batteryFraction < 0)
            return "battery"
        if (batteryFraction <= 0.20)
            return "battery-25"
        if (batteryFraction <= 0.45)
            return "battery-50"
        if (batteryFraction <= 0.75)
            return "battery-75"
        return "battery-full"
    }

    readonly property string statusText: {
        if (statusOverride.length > 0)
            return statusOverride
        if (name === "wifi")
            return "Wi-Fi connected"
        if (name === "keyboard")
            return "Click to switch keyboard layout"
        if (name === "battery") {
            if (batteryFraction < 0)
                return "Battery status unavailable"
            const percent = Math.round(batteryFraction * 100)
            if (batteryFull)
                return percent + "% · Fully charged"
            if (batteryCharging)
                return percent + "% · Charging"
            return percent + "% · On battery"
        }
        return ""
    }

    Image {
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        source: Quickshell.shellPath("icons/" + root.resolvedName + ".svg")
        opacity: root.iconOpacity
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: false
        sourceSize.width: Math.max(24, Math.ceil(width * 2))
        sourceSize.height: Math.max(24, Math.ceil(height * 2))
    }

    Rectangle {
        id: statusBubble
        visible: root.statusInteractive && root.statusOpen
        z: 1000
        anchors.top: parent.bottom
        anchors.topMargin: 9
        anchors.right: parent.right
        width: 194
        height: 54
        radius: 17
        color: Qt.rgba(0.09, 0.11, 0.15, 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.14)
        opacity: root.statusOpen ? 1 : 0
        scale: root.statusOpen ? 1 : 0.96

        Behavior on opacity {
            NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
        }

        Behavior on scale {
            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
        }

        Text {
            anchors.fill: parent
            anchors.leftMargin: 15
            anchors.rightMargin: 15
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignLeft
            text: root.statusText
            color: Qt.rgba(1, 1, 1, 0.91)
            font.pixelSize: 12
            wrapMode: Text.WordWrap
        }
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: root.statusInteractive
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor

        onClicked: {
            root.statusOverride = ""
            root.statusOpen = !root.statusOpen

            if (root.name === "keyboard") {
                if (!keyboardSwitch.running)
                    keyboardSwitch.exec(["hyprctl", "switchxkblayout", "all", "next"])
                root.statusOverride = "Switching keyboard layout…"
            }

            if (root.statusOpen)
                closeTimer.restart()
        }
    }

    Process {
        id: keyboardSwitch
        onExited: {
            root.statusOverride = "Layout switched"
            closeTimer.restart()
        }
    }

    Timer {
        id: closeTimer
        interval: 1800
        repeat: false
        onTriggered: root.statusOpen = false
    }
}
