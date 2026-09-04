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

    // Keep the compact target composition, but optically spread the outer
    // Wi-Fi/keyboard controls so the three status groups do not read as one
    // cramped icon cluster. Battery stays centered with its percentage label.
    readonly property real visualNudgeX: {
        if (name === "wifi")
            return -3
        if (name === "keyboard")
            return 3
        return 0
    }

    // Desktop-sized semantic hit targets. Battery/keyboard deliberately extend
    // over the sibling text rendered by the parent Row, so 100% and US are not
    // dead zones even though the visible glyph remains restrained.
    readonly property real interactionWidth: {
        if (name === "battery")
            return 69
        if (name === "keyboard")
            return 55
        if (name === "wifi")
            return 40
        return width
    }
    readonly property real interactionHeight: statusInteractive ? 44 : height
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
            if (!keyboardSwitch.running) {
                keyboardSwitch.exec([
                    "python",
                    Quickshell.shellPath("state.py"),
                    "--switch-layout",
                ])
            }
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

    Rectangle {
        id: interactionPlate
        x: root.interactionLeft + root.visualNudgeX
        y: root.interactionTop
        width: root.interactionWidth
        height: root.interactionHeight
        radius: height / 2
        visible: root.statusInteractive
        color: root.pressed
            ? Qt.rgba(1, 1, 1, 0.115)
            : (root.hovered || root.statusOpen
                ? Qt.rgba(1, 1, 1, 0.062)
                : "transparent")
        border.width: root.statusOpen ? 1 : 0
        border.color: Qt.rgba(1, 1, 1, 0.10)

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
        transform: Translate { x: root.visualNudgeX }
        scale: root.pressed
            ? 0.95
            : (root.hovered || root.statusOpen
                ? (root.statusInteractive ? 1.16 : 1.075)
                : (root.statusInteractive ? 1.10 : 1))

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
            sourceSize.width: Math.max(40, Math.ceil(width * 2.5))
            sourceSize.height: Math.max(40, Math.ceil(height * 2.5))
        }
    }

    SequentialAnimation {
        running: root.name === "battery" && root.batteryCharging
        loops: Animation.Infinite

        NumberAnimation {
            target: root
            property: "chargingPulse"
            to: 0.82
            duration: 760
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: root
            property: "chargingPulse"
            to: 1
            duration: 760
            easing.type: Easing.InOutSine
        }
    }

    Rectangle {
        id: statusBubble
        z: 1000
        anchors.top: parent.bottom
        anchors.topMargin: 16
        anchors.right: parent.right
        width: 250
        height: 78
        radius: 22
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
            width: 40
            height: 40
            radius: 20
            color: Qt.rgba(1, 1, 1, 0.072)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.09)

            Image {
                anchors.centerIn: parent
                width: 21
                height: 21
                source: Quickshell.shellPath("icons/" + root.resolvedName + ".svg")
                opacity: 0.93
                fillMode: Image.PreserveAspectFit
                smooth: true
                mipmap: true
                sourceSize.width: 52
                sourceSize.height: 52
            }
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 66
            anchors.top: parent.top
            anchors.topMargin: 17
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
            anchors.leftMargin: 66
            anchors.top: parent.top
            anchors.topMargin: 42
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
        x: root.interactionLeft + root.visualNudgeX
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
