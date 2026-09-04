import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

Item {
    id: root

    property string name: "lock"
    property real iconOpacity: 0.82
    property bool statusOpen: false
    property string statusTitle: ""
    property string statusDetail: ""
    property real chargingPulse: 1

    readonly property bool hovered: pointer.containsMouse
    readonly property bool pressed: pointer.pressed

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

    // The visible icon stays restrained, but the whole status control receives
    // a desktop-sized hit target. Battery/keyboard targets intentionally extend
    // over their sibling text labels so "100%" and "US" are clickable too.
    readonly property real interactionWidth: {
        if (name === "battery")
            return 69
        if (name === "keyboard")
            return 55
        if (name === "wifi")
            return 40
        return width
    }
    readonly property real interactionHeight: statusInteractive ? 42 : height
    readonly property real interactionLeft: statusInteractive ? -9 : 0
    readonly property real interactionTop:
        statusInteractive ? (height - interactionHeight) / 2 : 0

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

    readonly property string batteryText: {
        if (batteryFraction < 0)
            return "Battery status unavailable"
        const percent = Math.round(batteryFraction * 100)
        if (batteryFull)
            return percent + "% · Fully charged"
        if (batteryCharging)
            return percent + "% · Charging"
        return percent + "% · On battery"
    }

    function showStatus(title, detail) {
        statusTitle = title
        statusDetail = detail
        statusOpen = true
        closeTimer.restart()
    }

    function activateStatus() {
        if (!statusInteractive)
            return

        if (name === "keyboard") {
            showStatus("Keyboard", "Switching to next layout…")
            if (!keyboardSwitch.running)
                keyboardSwitch.exec([
                    "python",
                    Quickshell.shellPath("state.py"),
                    "--switch-layout",
                ])
            return
        }

        if (statusOpen) {
            statusOpen = false
            closeTimer.stop()
            return
        }

        if (name === "wifi") {
            showStatus(
                "Wi-Fi",
                "Connected · Manage in Maho Link after unlock"
            )
            return
        }

        if (name === "battery")
            showStatus("Battery", batteryText)
    }

    onBatteryChargingChanged: {
        if (!batteryCharging)
            chargingPulse = 1
    }

    // One quiet hover plate covers the complete semantic control, including the
    // adjacent percentage/layout text rendered by the parent Row.
    Rectangle {
        id: interactionPlate
        x: root.interactionLeft
        y: root.interactionTop
        width: root.interactionWidth
        height: root.interactionHeight
        radius: height / 2
        visible: root.statusInteractive
        color: root.pressed
            ? Qt.rgba(1, 1, 1, 0.125)
            : (root.hovered || root.statusOpen
                ? Qt.rgba(1, 1, 1, 0.070)
                : "transparent")
        border.width: root.statusOpen ? 1 : 0
        border.color: Qt.rgba(1, 1, 1, 0.105)
        opacity: root.statusInteractive ? 1 : 0

        Behavior on color {
            ColorAnimation { duration: 125; easing.type: Easing.OutCubic }
        }
        Behavior on border.color {
            ColorAnimation { duration: 125; easing.type: Easing.OutCubic }
        }
    }

    Item {
        id: iconVisual
        anchors.fill: parent
        scale: root.pressed
            ? 0.94
            : (root.hovered || root.statusOpen
                ? (root.statusInteractive ? 1.14 : 1.075)
                : (root.statusInteractive ? 1.075 : 1))

        Behavior on scale {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        Image {
            anchors.centerIn: parent
            width: parent.width
            height: parent.height
            source: Quickshell.shellPath("icons/" + root.resolvedName + ".svg")
            opacity: root.iconOpacity * root.chargingPulse
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            asynchronous: false
            sourceSize.width: Math.max(32, Math.ceil(width * 2.5))
            sourceSize.height: Math.max(32, Math.ceil(height * 2.5))
        }
    }

    SequentialAnimation {
        running: root.name === "battery" && root.batteryCharging
        loops: Animation.Infinite

        NumberAnimation {
            target: root
            property: "chargingPulse"
            to: 0.70
            duration: 720
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: root
            property: "chargingPulse"
            to: 1
            duration: 720
            easing.type: Easing.InOutSine
        }
    }

    Rectangle {
        id: statusBubble
        z: 1000
        anchors.top: parent.bottom
        anchors.topMargin: 15
        anchors.right: parent.right
        width: 246
        height: 76
        radius: 21
        visible: root.statusOpen || opacity > 0.001
        opacity: root.statusOpen ? 1 : 0
        scale: root.statusOpen ? 1 : 0.965
        color: Qt.rgba(0.070, 0.085, 0.115, 0.90)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.15)

        transform: Translate {
            y: root.statusOpen ? 0 : -5
            Behavior on y {
                NumberAnimation { duration: 155; easing.type: Easing.OutCubic }
            }
        }

        Behavior on opacity {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        Behavior on scale {
            NumberAnimation { duration: 165; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 14
            width: 38
            height: 38
            radius: 19
            color: Qt.rgba(1, 1, 1, 0.075)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.09)

            Image {
                anchors.centerIn: parent
                width: 20
                height: 20
                source: Quickshell.shellPath("icons/" + root.resolvedName + ".svg")
                opacity: 0.93
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                sourceSize.width: 50
                sourceSize.height: 50
            }
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 63
            anchors.top: parent.top
            anchors.topMargin: 16
            anchors.right: parent.right
            anchors.rightMargin: 14
            text: root.statusTitle
            color: Qt.rgba(1, 1, 1, 0.96)
            font.pixelSize: 13
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 63
            anchors.top: parent.top
            anchors.topMargin: 40
            anchors.right: parent.right
            anchors.rightMargin: 14
            text: root.statusDetail
            color: Qt.rgba(1, 1, 1, 0.63)
            font.pixelSize: 11
            elide: Text.ElideRight
        }
    }

    MouseArea {
        id: pointer
        z: 200
        x: root.interactionLeft
        y: root.interactionTop
        width: root.interactionWidth
        height: root.interactionHeight
        enabled: root.statusInteractive
        hoverEnabled: true
        cursorShape: root.statusInteractive
            ? Qt.PointingHandCursor
            : Qt.ArrowCursor
        onClicked: root.activateStatus()
    }

    Process {
        id: keyboardSwitch

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    const layout = String(payload.keyboardLayout || "").trim()
                    root.showStatus(
                        "Keyboard",
                        layout.length > 0
                            ? layout + " · Active layout"
                            : "Layout switched"
                    )
                } catch (error) {
                    root.showStatus("Keyboard", "Layout switched")
                }
            }
        }
    }

    Timer {
        id: closeTimer
        interval: 2800
        repeat: false
        onTriggered: root.statusOpen = false
    }
}
