import QtQuick

Item {
    id: root

    required property var chrome
    required property var bluetooth

    signal detailsRequested(var device)
    signal pairRequested(var device)

    readonly property var primaryDevice:
        bluetooth.connectedDevices && bluetooth.connectedDevices.length > 0
            ? bluetooth.connectedDevices[0]
            : null
    readonly property int pairedCount:
        bluetooth.pairedDevices ? bluetooth.pairedDevices.length : 0
    readonly property int nearbyCount:
        bluetooth.availableDevices ? bluetooth.availableDevices.length : 0

    // Bluetooth should read as neutral material with state-colored accents,
    // rather than tinting every surface with the wallpaper primary color.
    readonly property color glassLow: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.58),
        0.69
    )
    readonly property color glassRaised: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.40),
        0.78
    )
    readonly property color glassStroke: chrome.theme.alpha(chrome.theme.foreground, 0.045)
    readonly property color glassHighlight: chrome.theme.alpha(chrome.theme.foreground, 0.052)

    function glyph(kind) {
        switch (String(kind || "generic")) {
        case "headphones": return "󰋋"
        case "speaker": return "󰓃"
        case "keyboard": return "󰌌"
        case "mouse": return "󰍽"
        case "controller": return "󰊴"
        case "phone": return "󰏲"
        case "computer": return "󰍹"
        default: return "󰂯"
        }
    }

    Column {
        anchors.fill: parent
        spacing: 11

        Rectangle {
            width: parent.width
            height: 58
            radius: 17
            color: chrome.theme.alpha(
                chrome.mix(
                    chrome.theme.surfaceHigh,
                    root.bluetooth.bluetoothEnabled ? chrome.accent : chrome.theme.background,
                    root.bluetooth.bluetoothEnabled ? 0.035 : 0.12
                ),
                0.70
            )
            border.width: 1
            border.color: root.glassStroke

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.top: parent.top
                height: 1
                color: root.glassHighlight
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                width: 34
                height: 34
                radius: 12
                color: chrome.theme.alpha(
                    chrome.mix(
                        chrome.theme.surfaceHigh,
                        root.bluetooth.bluetoothEnabled ? chrome.accent : chrome.theme.background,
                        root.bluetooth.bluetoothEnabled ? 0.14 : 0.18
                    ),
                    0.76
                )
                border.width: 1
                border.color: chrome.theme.alpha(
                    root.bluetooth.bluetoothEnabled ? chrome.accent : chrome.theme.foreground,
                    root.bluetooth.bluetoothEnabled ? 0.11 : 0.04
                )

                Text {
                    anchors.centerIn: parent
                    text: "󰂯"
                    color: root.bluetooth.bluetoothEnabled
                        ? chrome.accent
                        : chrome.theme.alpha(chrome.textSecondary, 0.86)
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 19
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 59
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2

                Text {
                    text: "Bluetooth"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
                Text {
                    text: !root.bluetooth.available ? "Adapter unavailable"
                        : root.bluetooth.bluetoothEnabled ? "On" : "Off"
                    color: chrome.theme.alpha(chrome.textSecondary, 0.68)
                    font.family: "Inter"
                    font.pixelSize: 10
                }
            }

            Rectangle {
                id: toggleTrack
                anchors.right: parent.right
                anchors.rightMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                width: 46
                height: 27
                radius: 14
                opacity: root.bluetooth.available && !root.bluetooth.busy ? 1 : 0.48
                color: root.bluetooth.bluetoothEnabled
                    ? chrome.theme.alpha(chrome.accent, toggleHover.containsMouse ? 0.74 : 0.64)
                    : chrome.theme.alpha(chrome.theme.surfaceHigh, 0.54)
                border.width: 1
                border.color: root.bluetooth.bluetoothEnabled
                    ? chrome.theme.alpha(chrome.accent, 0.18)
                    : chrome.theme.alpha(chrome.theme.foreground, 0.05)

                Behavior on color { ColorAnimation { duration: 150 } }

                Rectangle {
                    width: 22
                    height: 22
                    radius: 11
                    y: 4
                    x: root.bluetooth.bluetoothEnabled ? parent.width - width - 2 : 2
                    color: Qt.rgba(0, 0, 0, 0.16)
                    opacity: 0.7
                    Behavior on x { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
                }

                Rectangle {
                    width: 21
                    height: 21
                    radius: 11
                    y: 3
                    x: root.bluetooth.bluetoothEnabled ? parent.width - width - 3 : 3
                    color: Qt.rgba(0.985, 0.985, 0.985, 0.98)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.38)
                    Behavior on x { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
                }

                MouseArea {
                    id: toggleHover
                    anchors.fill: parent
                    enabled: root.bluetooth.available && !root.bluetooth.busy
                    hoverEnabled: true
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.bluetooth.setBluetoothEnabled(!root.bluetooth.bluetoothEnabled)
                }
            }
        }

        Rectangle {
            id: hero
            width: parent.width
            height: root.primaryDevice ? 118 : 0
            visible: root.primaryDevice !== null
            radius: 18
            color: heroHover.containsMouse
                ? chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.045), 0.82)
                : root.glassRaised
            border.width: 1
            border.color: heroHover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.13)
                : root.glassStroke
            clip: true

            Behavior on color { ColorAnimation { duration: 150 } }
            Behavior on border.color { ColorAnimation { duration: 150 } }

            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.accent, 0.050) }
                    GradientStop { position: 0.52; color: chrome.theme.alpha(chrome.accent, 0.012) }
                    GradientStop { position: 1; color: "transparent" }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.top: parent.top
                height: 1
                color: chrome.theme.alpha(chrome.theme.foreground, 0.065)
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: root.primaryDevice !== null
                    && String(root.primaryDevice.quality || "") !== "" ? -14 : 0
                width: 70
                height: 70
                radius: 22
                color: chrome.theme.alpha(
                    chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.08),
                    0.72
                )
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.foreground, 0.055)

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    anchors.top: parent.top
                    height: 1
                    color: chrome.theme.alpha(chrome.theme.foreground, 0.07)
                }

                Text {
                    anchors.centerIn: parent
                    text: root.glyph(root.primaryDevice ? root.primaryDevice.kind : "generic")
                    color: chrome.theme.alpha(chrome.textPrimary, 0.94)
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 34
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 105
                anchors.right: parent.right
                anchors.rightMargin: 48
                anchors.top: parent.top
                anchors.topMargin: 20
                spacing: 5

                Text {
                    width: parent.width
                    text: root.primaryDevice ? String(root.primaryDevice.name || "Bluetooth Device") : ""
                    color: chrome.textPrimary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Connected"
                    color: chrome.theme.alpha(chrome.accent, 0.88)
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
                Text {
                    visible: root.primaryDevice !== null
                        && root.primaryDevice.battery !== null
                        && root.primaryDevice.battery !== undefined
                    text: visible ? String(root.primaryDevice.battery) + "% Battery" : ""
                    color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                    font.family: "Inter"
                    font.pixelSize: 11
                }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: root.primaryDevice !== null
                    && String(root.primaryDevice.quality || "") !== "" ? -14 : 0
                text: "›"
                color: heroHover.containsMouse
                    ? chrome.theme.alpha(chrome.textPrimary, 0.78)
                    : chrome.theme.alpha(chrome.textSecondary, 0.62)
                font.family: "Inter"
                font.pixelSize: 24
                font.weight: Font.Light
            }

            Item {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 34
                visible: root.primaryDevice !== null && String(root.primaryDevice.quality || "") !== ""

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 18
                    anchors.rightMargin: 18
                    height: 1
                    color: chrome.theme.alpha(chrome.theme.foreground, 0.040)
                }

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Connection Quality"
                    color: chrome.theme.alpha(chrome.textSecondary, 0.68)
                    font.family: "Inter"
                    font.pixelSize: 10
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.primaryDevice ? String(root.primaryDevice.quality || "") : ""
                    color: chrome.theme.alpha(chrome.textPrimary, 0.86)
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }
            }

            MouseArea {
                id: heroHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.detailsRequested(root.primaryDevice)
            }
        }

        Item {
            width: parent.width
            height: root.bluetooth.bluetoothEnabled ? 20 : 0
            visible: root.bluetooth.bluetoothEnabled

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "Paired Devices"
                color: chrome.theme.alpha(chrome.textSecondary, 0.76)
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }
        }

        Rectangle {
            width: parent.width
            height: !root.bluetooth.bluetoothEnabled ? 176
                : root.pairedCount > 0 ? Math.min(144, root.pairedCount * 55 + 6) : 94
            radius: 17
            color: root.glassLow
            border.width: 1
            border.color: root.glassStroke
            clip: true

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.top: parent.top
                height: 1
                color: root.glassHighlight
            }

            ListView {
                id: pairedList
                anchors.fill: parent
                anchors.margins: 3
                visible: root.bluetooth.bluetoothEnabled && root.pairedCount > 0
                model: root.bluetooth.pairedDevices || []
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                delegate: Item {
                    required property var modelData
                    width: pairedList.width
                    height: 55

                    BluetoothDeviceRow {
                        anchors.fill: parent
                        chrome: root.chrome
                        device: modelData
                        interactionEnabled: !root.bluetooth.busy
                        onSelected: root.detailsRequested(modelData)
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 58
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.bottom: parent.bottom
                        height: 1
                        color: chrome.theme.alpha(chrome.theme.foreground, 0.035)
                    }
                }
            }

            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - 60, 330)
                spacing: 7
                visible: !root.bluetooth.bluetoothEnabled || root.pairedCount === 0

                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: !root.bluetooth.available ? "Bluetooth unavailable"
                        : !root.bluetooth.bluetoothEnabled ? "Bluetooth is Off"
                        : !root.bluetooth.snapshotReady ? "Reading devices…"
                        : "No Paired Devices"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 12
                    font.weight: Font.Medium
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: !root.bluetooth.bluetoothEnabled
                        ? "Turn on Bluetooth to connect accessories and nearby devices."
                        : "Nearby devices will appear below while Bluetooth is discovering."
                    color: chrome.theme.alpha(chrome.textSecondary, 0.62)
                    font.family: "Inter"
                    font.pixelSize: 10
                    lineHeight: 1.25
                }
            }
        }

        Item {
            width: parent.width
            height: root.bluetooth.bluetoothEnabled ? 24 : 0
            visible: root.bluetooth.bluetoothEnabled

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "Available Devices"
                color: chrome.theme.alpha(chrome.textSecondary, 0.76)
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 7

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    visible: root.bluetooth.discovering
                    color: chrome.accent
                    opacity: 0.75

                    SequentialAnimation on opacity {
                        running: root.bluetooth.discovering
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.28; duration: 650; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 0.85; duration: 650; easing.type: Easing.InOutSine }
                    }
                }

                Text {
                    text: root.bluetooth.discovering ? "Looking…" : "Find Devices"
                    color: chrome.theme.alpha(chrome.accent, 0.90)
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium

                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -8
                        enabled: !root.bluetooth.busy
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            if (root.bluetooth.discovering)
                                root.bluetooth.stopDiscovery()
                            else
                                root.bluetooth.startDiscovery()
                        }
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: root.bluetooth.bluetoothEnabled ? 104 : 0
            visible: root.bluetooth.bluetoothEnabled
            radius: 17
            color: root.glassLow
            border.width: 1
            border.color: root.glassStroke
            clip: true

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.top: parent.top
                height: 1
                color: root.glassHighlight
            }

            ListView {
                id: nearbyList
                anchors.fill: parent
                anchors.margins: 3
                model: root.bluetooth.availableDevices || []
                boundsBehavior: Flickable.StopAtBounds
                clip: true

                delegate: Item {
                    required property var modelData
                    width: nearbyList.width
                    height: 55

                    BluetoothDeviceRow {
                        anchors.fill: parent
                        chrome: root.chrome
                        device: modelData
                        actionLabel: "Pair"
                        interactionEnabled: !root.bluetooth.busy
                        onSelected: root.pairRequested(modelData)
                        onActionRequested: root.pairRequested(modelData)
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 6
                    visible: nearbyList.count === 0

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.bluetooth.discovering ? "󰂯" : "󰂲"
                        color: chrome.theme.alpha(
                            root.bluetooth.discovering ? chrome.accent : chrome.textSecondary,
                            root.bluetooth.discovering ? 0.78 : 0.42
                        )
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 18
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.bluetooth.discovering ? "Looking for nearby devices…" : "No nearby devices found"
                        color: chrome.theme.alpha(chrome.textSecondary, 0.62)
                        font.family: "Inter"
                        font.pixelSize: 10
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: root.bluetooth.bluetoothEnabled ? 45 : 0
            visible: root.bluetooth.bluetoothEnabled
            radius: 15
            color: pairHover.pressed
                ? chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.08), 0.76)
                : pairHover.containsMouse
                    ? chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.045), 0.72)
                    : root.glassLow
            border.width: 1
            border.color: pairHover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.12)
                : root.glassStroke

            Behavior on color { ColorAnimation { duration: 125 } }
            Behavior on border.color { ColorAnimation { duration: 125 } }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 13
                anchors.verticalCenter: parent.verticalCenter
                width: 28
                height: 28
                radius: 10
                color: chrome.theme.alpha(chrome.accent, 0.075)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.08)

                Text {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -1
                    text: "+"
                    color: chrome.accent
                    font.family: "Inter"
                    font.pixelSize: 18
                    font.weight: Font.Light
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 52
                anchors.verticalCenter: parent.verticalCenter
                text: root.bluetooth.discovering ? "Discovering Nearby Devices" : "Pair New Device"
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: root.bluetooth.discovering ? "•••" : "›"
                color: chrome.theme.alpha(chrome.textSecondary, 0.55)
                font.family: "Inter"
                font.pixelSize: root.bluetooth.discovering ? 11 : 20
                font.weight: Font.Light
            }

            MouseArea {
                id: pairHover
                anchors.fill: parent
                enabled: !root.bluetooth.busy
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (!root.bluetooth.discovering)
                        root.bluetooth.startDiscovery()
                }
            }
        }
    }
}
