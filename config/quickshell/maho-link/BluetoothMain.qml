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
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.accent, 0.055), 0.97)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.07)

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                width: 34
                height: 34
                radius: 12
                color: chrome.theme.alpha(
                    root.bluetooth.bluetoothEnabled ? chrome.accent : chrome.textSecondary,
                    root.bluetooth.bluetoothEnabled ? 0.14 : 0.08
                )

                Text {
                    anchors.centerIn: parent
                    text: "󰂯"
                    color: root.bluetooth.bluetoothEnabled ? chrome.accent : chrome.textSecondary
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
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 10
                }
            }

            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                width: 46
                height: 27
                radius: 14
                opacity: root.bluetooth.available && !root.bluetooth.busy ? 1 : 0.48
                color: root.bluetooth.bluetoothEnabled
                    ? chrome.theme.alpha(chrome.accent, toggleHover.containsMouse ? 0.88 : 0.76)
                    : chrome.theme.alpha(chrome.textSecondary, 0.14)
                border.width: 1
                border.color: root.bluetooth.bluetoothEnabled
                    ? chrome.theme.alpha(chrome.accent, 0.20)
                    : chrome.theme.alpha(chrome.theme.outline, 0.10)

                Rectangle {
                    width: 21
                    height: 21
                    radius: 11
                    y: 3
                    x: root.bluetooth.bluetoothEnabled ? parent.width - width - 3 : 3
                    color: Qt.rgba(1, 1, 1, 0.94)
                    Behavior on x { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
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
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.accent, 0.105), 0.975)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.accent, 0.105)
            clip: true

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: 70
                height: 70
                radius: 22
                color: chrome.theme.alpha(chrome.accent, 0.105)

                Text {
                    anchors.centerIn: parent
                    text: root.glyph(root.primaryDevice ? root.primaryDevice.kind : "generic")
                    color: chrome.theme.alpha(chrome.textPrimary, 0.92)
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
                    color: chrome.accent
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }
                Text {
                    visible: root.primaryDevice !== null
                        && root.primaryDevice.battery !== null
                        && root.primaryDevice.battery !== undefined
                    text: visible ? String(root.primaryDevice.battery) + "% Battery" : ""
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 11
                }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: chrome.textSecondary
                font.family: "Inter"
                font.pixelSize: 25
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 34
                visible: root.primaryDevice !== null && String(root.primaryDevice.quality || "") !== ""
                color: chrome.theme.alpha(chrome.theme.background, 0.13)

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Connection Quality"
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 10
                }
                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.primaryDevice ? String(root.primaryDevice.quality || "") : ""
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }
            }

            MouseArea {
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
                color: chrome.textSecondary
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
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.theme.background, 0.08), 0.965)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.065)
            clip: true

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
                        color: chrome.theme.alpha(chrome.theme.outline, 0.055)
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
                    color: chrome.theme.alpha(chrome.textSecondary, 0.72)
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
                color: chrome.textSecondary
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
                    color: chrome.accent
                    font.family: "Inter"
                    font.pixelSize: 10

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
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.theme.background, 0.08), 0.965)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.065)
            clip: true

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

                Text {
                    anchors.centerIn: parent
                    visible: nearbyList.count === 0
                    text: root.bluetooth.discovering ? "Looking for nearby devices…" : "No nearby devices found"
                    color: chrome.theme.alpha(chrome.textSecondary, 0.72)
                    font.family: "Inter"
                    font.pixelSize: 10
                }
            }
        }

        Rectangle {
            width: parent.width
            height: root.bluetooth.bluetoothEnabled ? 45 : 0
            visible: root.bluetooth.bluetoothEnabled
            radius: 15
            color: pairHover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.085)
                : chrome.theme.alpha(chrome.insetColor, 0.86)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.06)

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                text: "+"
                color: chrome.accent
                font.family: "Inter"
                font.pixelSize: 20
            }
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 44
                anchors.verticalCenter: parent.verticalCenter
                text: root.bluetooth.discovering ? "Discovering Nearby Devices" : "Pair New Device"
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
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
