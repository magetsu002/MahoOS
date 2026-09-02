import QtQuick

Item {
    id: root

    required property var chrome
    required property var bluetooth
    required property var device

    signal forgetRequested()

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

    readonly property bool hasBattery:
        device && device.battery !== null && device.battery !== undefined
    readonly property bool hasQuality:
        device && String(device.quality || "") !== ""

    Column {
        anchors.fill: parent
        spacing: 13

        Rectangle {
            width: parent.width
            height: 130
            radius: 19
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.accent, 0.095), 0.975)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.accent, 0.10)

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: 80
                height: 80
                radius: 25
                color: chrome.theme.alpha(chrome.accent, 0.105)

                Text {
                    anchors.centerIn: parent
                    text: root.glyph(device ? device.kind : "generic")
                    color: chrome.textPrimary
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 37
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 118
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                Text {
                    width: parent.width
                    text: String(device && device.name ? device.name : "Bluetooth Device")
                    color: chrome.textPrimary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }

                Text {
                    text: device && device.connected ? "Connected" : "Not Connected"
                    color: device && device.connected ? chrome.accent : chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }

                Text {
                    visible: root.hasBattery
                    text: visible ? String(device.battery) + "% Battery" : ""
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 11
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 53 + (root.hasQuality ? 53 : 0) + (root.hasBattery ? 53 : 0)
            radius: 18
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.theme.background, 0.08), 0.965)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.065)
            clip: true

            Column {
                anchors.fill: parent

                Item {
                    width: parent.width
                    height: 53
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Device Type"
                        color: chrome.textSecondary
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(device && device.type ? device.type : "Bluetooth Device")
                        color: chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }

                Rectangle {
                    width: parent.width - 34
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 1
                    visible: root.hasQuality || root.hasBattery
                    color: chrome.theme.alpha(chrome.theme.outline, 0.06)
                }

                Item {
                    width: parent.width
                    height: root.hasQuality ? 53 : 0
                    visible: root.hasQuality
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Connection Quality"
                        color: chrome.textSecondary
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(device && device.quality ? device.quality : "")
                        color: chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }

                Rectangle {
                    width: parent.width - 34
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 1
                    visible: root.hasQuality && root.hasBattery
                    color: chrome.theme.alpha(chrome.theme.outline, 0.06)
                }

                Item {
                    width: parent.width
                    height: root.hasBattery ? 53 : 0
                    visible: root.hasBattery
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Battery"
                        color: chrome.textSecondary
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.hasBattery ? String(device.battery) + "%" : ""
                        color: chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 104
            radius: 18
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.theme.background, 0.08), 0.965)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.065)
            clip: true

            Column {
                anchors.fill: parent

                Item {
                    width: parent.width
                    height: 52

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 3
                        radius: 13
                        color: connectHover.containsMouse
                            ? chrome.theme.alpha(chrome.accent, 0.06)
                            : "transparent"
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: device && device.connected ? "󰂲" : "󰂱"
                        color: chrome.textSecondary
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 16
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 48
                        anchors.verticalCenter: parent.verticalCenter
                        text: device && device.connected ? "Disconnect" : "Connect"
                        color: chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        id: connectHover
                        anchors.fill: parent
                        enabled: !root.bluetooth.busy
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            if (device && device.connected)
                                root.bluetooth.disconnectDevice(device)
                            else
                                root.bluetooth.connectDevice(device)
                        }
                    }
                }

                Rectangle {
                    width: parent.width - 34
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 1
                    color: chrome.theme.alpha(chrome.theme.outline, 0.06)
                }

                Item {
                    width: parent.width
                    height: 51

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 3
                        radius: 13
                        color: forgetHover.containsMouse
                            ? chrome.theme.alpha(chrome.theme.error, 0.075)
                            : "transparent"
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: "󰆴"
                        color: chrome.theme.error
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 15
                    }
                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 48
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Forget Device"
                        color: chrome.theme.error
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        id: forgetHover
                        anchors.fill: parent
                        enabled: !root.bluetooth.busy
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.forgetRequested()
                    }
                }
            }
        }
    }
}
