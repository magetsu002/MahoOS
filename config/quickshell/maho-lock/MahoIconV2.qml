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
    readonly property bool statusParticipant: statusInteractive

    // The visible glyphs move apart slightly, but layout remains anchored to
    // the accepted compact target composition.
    readonly property real visualNudgeX: {
        if (name === "wifi")
            return -2
        if (name === "keyboard")
            return 2
        return 0
    }

    // Hit geometry and hover geometry are deliberately separate. The pointer
    // stays large enough to include the adjacent 100% / layout text, but each
    // semantic target stops before its neighbor so two controls can never be
    // hovered at once. The visible hover capsule is smaller again, preserving
    // clear negative space between Wi-Fi, battery and keyboard.
    readonly property real interactionWidth: {
        if (name === "battery")
            return 64
        if (name === "keyboard")
            return 52
        if (name === "wifi")
            return 34
        return width
    }
    readonly property real interactionHeight: statusInteractive ? 42 : height
    readonly property real interactionLeft: {
        if (name === "keyboard")
            return -6
        if (statusInteractive)
            return -7
        return 0
    }
    readonly property real interactionTop:
        statusInteractive ? (height - interactionHeight) / 2 : 0

    readonly property real hoverWidth: {
        if (name === "battery")
            return 58
        if (name === "keyboard")
            return 46
        if (name === "wifi")
            return 30
        return width
    }
    readonly property real hoverHeight: statusInteractive ? 34 : height
    readonly property real hoverLeft: {
        if (name === "battery")
            return -4
        if (name === "keyboard")
            return -3
        if (name === "wifi")
            return -5
        return 0
    }
    readonly property real hoverTop:
        statusInteractive ? (height - hoverHeight) / 2 : 0

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

    function rootItem() {
        let node = root
        while (node.parent)
            node = node.parent
        return node
    }

    function closePeerStatuses(node) {
        if (!node || !node.children)
            return

        const children = node.children
        for (let index = 0; index < children.length; index++) {
            const child = children[index]
            if (child !== root
                && child.statusParticipant === true
                && child.statusOpen === true) {
                child.statusOpen = false
            }
            closePeerStatuses(child)
        }
    }

    function showStatus(title, detail) {
        // One authority at a time: opening a status surface atomically closes
        // every peer Wi-Fi / battery / keyboard surface first.
        closePeerStatuses(rootItem())
        statusTitle = title
        statusDetail = detail
        statusOpen = true
        closeTimer.restart()
    }

    function activateStatus() {
        if (!statusInteractive)
            return

        if (statusOpen) {
            statusOpen = false
            closeTimer.stop()
            return
        }

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
        x: root.hoverLeft + root.visualNudgeX
        y: root.hoverTop
        width: root.hoverWidth
        height: root.hoverHeight
        radius: height / 2
        visible: root.statusInteractive
        color: root.pressed
            ? Qt.rgba(1, 1, 1, 0.105)
            : (root.hovered || root.statusOpen
                ? Qt.rgba(1, 1, 1, 0.056)
                : "transparent")
        border.width: root.statusOpen ? 1 : 0
        border.color: Qt.rgba(1, 1, 1, 0.095)

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
            ? 0.955
            : (root.hovered || root.statusOpen
                ? (root.statusInteractive ? 1.12 : 1.075)
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
            to: 0.84
            duration: 820
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: root
            property: "chargingPulse"
            to: 1
            duration: 820
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
        // Previous peers disappear immediately when another status control is
        // activated. That prevents the stacked-card mess seen in native preview.
        visible: root.statusOpen
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
