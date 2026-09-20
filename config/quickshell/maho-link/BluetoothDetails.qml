import QtQuick

Item {
    id: root

    required property var chrome
    required property var bluetooth
    required property var device

    signal forgetRequested()

    readonly property bool hasBattery:
        device && device.battery !== null && device.battery !== undefined
    readonly property bool hasQuality:
        device && String(device.quality || "") !== ""

    readonly property color glassLow: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.64),
        0.42
    )
    readonly property color glassRaised: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.48),
        0.54
    )
    readonly property color glassInteractive: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56),
        0.47
    )
    readonly property color glassStroke: chrome.theme.alpha(chrome.theme.foreground, 0.060)
    readonly property color glassHighlight: chrome.theme.alpha(chrome.theme.foreground, 0.060)
    readonly property color separator: chrome.theme.alpha(chrome.theme.foreground, 0.032)
    readonly property color lowlight: chrome.theme.alpha(chrome.theme.background, 0.10)

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
        spacing: 13

        Rectangle {
            id: heroCard
            width: parent.width
            height: 130
            radius: 20
            antialiasing: true
            color: root.glassRaised
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.foreground, 0.070)

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.035) }
                    GradientStop { position: 0.30; color: chrome.theme.alpha(chrome.accent, 0.040) }
                    GradientStop { position: 0.72; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.accent, 0.018) }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                anchors.top: parent.top
                height: 1
                radius: 1
                antialiasing: true
                color: chrome.theme.alpha(chrome.theme.foreground, 0.070)
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: 80
                height: 80
                radius: 26
                antialiasing: true
                color: chrome.theme.alpha(
                    chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.12),
                    0.50
                )
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.foreground, 0.075)

                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    antialiasing: true
                    gradient: Gradient {
                        GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.045) }
                        GradientStop { position: 0.58; color: "transparent" }
                        GradientStop { position: 1; color: chrome.theme.alpha(chrome.accent, 0.045) }
                    }
                }

                Text {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -1
                    text: root.glyph(device ? device.kind : "generic")
                    color: chrome.theme.alpha(chrome.textPrimary, 0.96)
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 37
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    renderType: Text.NativeRendering
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
                    color: device && device.connected
                        ? chrome.theme.alpha(chrome.accent, 0.90)
                        : chrome.theme.alpha(chrome.textSecondary, 0.72)
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium
                }

                Text {
                    visible: root.hasBattery
                    text: visible ? String(device.battery) + "% Battery" : ""
                    color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                    font.family: "Inter"
                    font.pixelSize: 11
                }
            }
        }

        Rectangle {
            id: infoCard
            width: parent.width
            height: 53 + (root.hasQuality ? 53 : 0) + (root.hasBattery ? 53 : 0)
            radius: 19
            antialiasing: true
            color: root.glassLow
            border.width: 1
            border.color: root.glassStroke

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.018) }
                    GradientStop { position: 0.58; color: "transparent" }
                    GradientStop { position: 1; color: root.lowlight }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                anchors.top: parent.top
                height: 1
                radius: 1
                antialiasing: true
                color: root.glassHighlight
            }

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
                        color: chrome.theme.alpha(chrome.textSecondary, 0.74)
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(device && device.type ? device.type : "Bluetooth Device")
                        color: chrome.theme.alpha(chrome.textPrimary, 0.91)
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }

                Rectangle {
                    width: parent.width - 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 1
                    visible: root.hasQuality || root.hasBattery
                    color: root.separator
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
                        color: chrome.theme.alpha(chrome.textSecondary, 0.74)
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(device && device.quality ? device.quality : "")
                        color: chrome.theme.alpha(chrome.textPrimary, 0.91)
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }

                Rectangle {
                    width: parent.width - 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 1
                    visible: root.hasQuality && root.hasBattery
                    color: root.separator
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
                        color: chrome.theme.alpha(chrome.textSecondary, 0.74)
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                    Text {
                        anchors.right: parent.right
                        anchors.rightMargin: 17
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.hasBattery ? String(device.battery) + "%" : ""
                        color: chrome.theme.alpha(chrome.textPrimary, 0.91)
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }
                }
            }
        }

        Rectangle {
            id: actionCard
            width: parent.width
            height: device && device.connected ? 157 : 104
            radius: 19
            antialiasing: true
            color: root.glassInteractive
            border.width: 1
            border.color: root.glassStroke

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.018) }
                    GradientStop { position: 0.60; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.accent, 0.012) }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                anchors.top: parent.top
                height: 1
                radius: 1
                antialiasing: true
                color: root.glassHighlight
            }

            Column {
                anchors.fill: parent

                Item {
                    width: parent.width
                    height: 52

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 3
                        radius: 15
                        antialiasing: true
                        scale: connectHover.pressed ? 0.996 : 1
                        color: "transparent"
                        Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }

                        Rectangle {
                            id: connectHoverPlane
                            anchors.fill: parent
                            radius: parent.radius
                            antialiasing: true
                            color: chrome.theme.alpha(chrome.theme.foreground, 0.032)
                            opacity: connectHover.containsMouse ? 1 : 0

                            Behavior on opacity {
                                NumberAnimation { duration: 125; easing.type: Easing.OutCubic }
                            }
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.verticalCenter: parent.verticalCenter
                        width: 30
                        height: 30
                        radius: 11
                        antialiasing: true
                        color: chrome.theme.alpha(chrome.theme.surfaceHigh, 0.28)
                        border.width: 1
                        border.color: chrome.theme.alpha(chrome.theme.foreground, 0.050)

                        Text {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -1
                            text: device && device.connected ? "󰑐" : "󰂱"
                            color: chrome.theme.alpha(chrome.textSecondary, 0.84)
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 15
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            renderType: Text.NativeRendering
                        }
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 54
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.bluetooth.activeAction === "reconnect"
                            ? "Reconnecting…"
                            : device && device.connected ? "Reconnect" : "Connect"
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
                                root.bluetooth.reconnectDevice(device)
                            else
                                root.bluetooth.connectDevice(device)
                        }
                    }
                }

                Rectangle {
                    width: parent.width - 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: 1
                    color: root.separator
                }

                Item {
                    width: parent.width
                    height: device && device.connected ? 52 : 0
                    visible: Boolean(device && device.connected)

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 3
                        radius: 15
                        antialiasing: true
                        scale: disconnectHover.pressed ? 0.996 : 1
                        color: "transparent"
                        Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }

                        Rectangle {
                            id: disconnectHoverPlane
                            anchors.fill: parent
                            radius: parent.radius
                            antialiasing: true
                            color: chrome.theme.alpha(chrome.theme.foreground, 0.032)
                            opacity: disconnectHover.containsMouse ? 1 : 0

                            Behavior on opacity {
                                NumberAnimation { duration: 125; easing.type: Easing.OutCubic }
                            }
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.verticalCenter: parent.verticalCenter
                        width: 30
                        height: 30
                        radius: 11
                        antialiasing: true
                        color: chrome.theme.alpha(chrome.theme.surfaceHigh, 0.28)
                        border.width: 1
                        border.color: chrome.theme.alpha(chrome.theme.foreground, 0.050)

                        Text {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -1
                            text: "󰂲"
                            color: chrome.theme.alpha(chrome.textSecondary, 0.84)
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 15
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            renderType: Text.NativeRendering
                        }
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 54
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.bluetooth.activeAction === "disconnect" ? "Disconnecting…" : "Disconnect"
                        color: chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        id: disconnectHover
                        anchors.fill: parent
                        enabled: !root.bluetooth.busy
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.bluetooth.disconnectDevice(device)
                    }
                }

                Rectangle {
                    width: parent.width - 42
                    anchors.horizontalCenter: parent.horizontalCenter
                    height: device && device.connected ? 1 : 0
                    visible: Boolean(device && device.connected)
                    color: root.separator
                }

                Item {
                    width: parent.width
                    height: 51

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 3
                        radius: 15
                        antialiasing: true
                        scale: forgetHover.pressed ? 0.996 : 1
                        color: "transparent"
                        Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }

                        Rectangle {
                            id: forgetHoverPlane
                            anchors.fill: parent
                            radius: parent.radius
                            antialiasing: true
                            color: chrome.theme.alpha(chrome.theme.error, 0.055)
                            opacity: forgetHover.containsMouse ? 1 : 0

                            Behavior on opacity {
                                NumberAnimation { duration: 125; easing.type: Easing.OutCubic }
                            }
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 13
                        anchors.verticalCenter: parent.verticalCenter
                        width: 30
                        height: 30
                        radius: 11
                        antialiasing: true
                        color: chrome.theme.alpha(chrome.theme.error, 0.055)
                        border.width: 1
                        border.color: chrome.theme.alpha(chrome.theme.error, 0.070)

                        Text {
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -1
                            text: "󰆴"
                            color: chrome.theme.error
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 14
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            renderType: Text.NativeRendering
                        }
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 54
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
