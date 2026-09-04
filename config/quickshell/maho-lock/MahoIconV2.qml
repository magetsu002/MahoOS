import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

Item {
    id: root

    property string name: "lock"
    property real iconOpacity: 0.82
    property string statusLabel: ""
    property real statusIconSize: Math.min(width, height)
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

    // A status control owns its complete rectangular cell. The hover plate and
    // pointer never extend into a neighboring control, so semantic hit targets
    // stay generous without producing overlapping hover capsules.
    Rectangle {
        id: interactionPlate
        anchors.fill: parent
        visible: root.statusInteractive
        radius: height / 2
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

    // Ordinary glyph mode for lock/edit/eye/etc. Interactive top-right status
    // controls use statusContent below so icon + wording are one real control.
    Item {
        anchors.fill: parent
        visible: !root.statusInteractive
        scale: root.pressed ? 0.95 : (root.hovered ? 1.075 : 1)

        Behavior on scale {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        Image {
            anchors.fill: parent
            source: Quickshell.shellPath("icons/" + root.resolvedName + ".svg")
            opacity: root.iconOpacity
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            asynchronous: false
            sourceSize.width: Math.max(40, Math.ceil(width * 2.5))
            sourceSize.height: Math.max(40, Math.ceil(height * 2.5))
        }
    }

    Row {
        id: statusContent
        anchors.centerIn: parent
        visible: root.statusInteractive
        spacing: root.statusLabel.length > 0 ? 6 : 0
        scale: root.pressed
            ? 0.955
            : (root.hovered || root.statusOpen ? 1.055 : 1)

        Behavior on scale {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        Image {
            width: root.statusIconSize
            height: root.statusIconSize
            anchors.verticalCenter: parent.verticalCenter
            source: Quickshell.shellPath("icons/" + root.resolvedName + ".svg")
            opacity: root.iconOpacity * root.chargingPulse
            fillMode: Image.PreserveAspectFit
            smooth: true
            mipmap: true
            asynchronous: false
            sourceSize.width: Math.max(48, Math.ceil(width * 2.75))
            sourceSize.height: Math.max(48, Math.ceil(height * 2.75))
        }

        Text {
            visible: root.statusLabel.length > 0
            anchors.verticalCenter: parent.verticalCenter
            text: root.statusLabel
            color: Qt.rgba(1, 1, 1, 0.96)
            font.pixelSize: 13
            font.weight: Font.Normal
            renderType: Text.NativeRendering
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
        anchors.fill: parent
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
