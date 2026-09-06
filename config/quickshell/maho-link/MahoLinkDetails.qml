import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi
    required property var network
    signal backRequested()

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
    readonly property color glassStroke: chrome.theme.alpha(chrome.theme.foreground, 0.055)
    readonly property color glassHighlight: chrome.theme.alpha(chrome.theme.foreground, 0.050)
    readonly property color separator: chrome.theme.alpha(chrome.theme.foreground, 0.028)

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 13

        Rectangle {
            width: parent.width
            height: 112
            radius: 20
            antialiasing: true
            color: root.glassRaised
            border.width: 1
            border.color: root.glassStroke

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.042) }
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
                color: root.glassHighlight
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: 66
                height: 66
                radius: 22
                antialiasing: true
                color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.12), 0.47)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.075)

                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    antialiasing: true
                    gradient: Gradient {
                        GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.045) }
                        GradientStop { position: 0.58; color: "transparent" }
                        GradientStop { position: 1; color: chrome.theme.alpha(chrome.accent, 0.036) }
                    }
                }

                MahoWifiGlyph {
                    anchors.centerIn: parent
                    width: 32
                    height: 32
                    glyphColor: chrome.theme.alpha(chrome.accent, 0.92)
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 104
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5

                Text {
                    width: parent.width
                    text: String(root.network.ssid || "Wi-Fi")
                    color: chrome.textPrimary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Connected"
                    color: chrome.theme.alpha(chrome.accent, 0.86)
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                Text {
                    text: String(root.network.quality || "")
                    color: chrome.theme.alpha(chrome.textSecondary, 0.68)
                    font.family: "Inter"
                    font.pixelSize: 11
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 190
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
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.020) }
                    GradientStop { position: 0.60; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.080) }
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
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                anchors.topMargin: 1
                anchors.bottomMargin: 1

                Repeater {
                    model: [
                        ["Signal", String(root.network.signal || 0) + "%"],
                        ["Security", String(root.network.security || "Unknown")],
                        ["Band", String(root.network.band || "Unknown")],
                        ["IPv4", String(root.network.ipv4 || "Unavailable")],
                        ["Router", String(root.network.gateway || "Unavailable")]
                    ]

                    Item {
                        required property var modelData
                        required property int index
                        width: parent.width
                        height: 37.6

                        Text {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData[0]
                            color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                            font.family: "Inter"
                            font.pixelSize: 10
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width * 0.64
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideMiddle
                            text: modelData[1]
                            color: chrome.theme.alpha(chrome.textPrimary, 0.90)
                            font.family: "Inter"
                            font.pixelSize: 10
                            font.weight: Font.Medium
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 2
                            anchors.right: parent.right
                            anchors.rightMargin: 2
                            anchors.bottom: parent.bottom
                            height: 1
                            visible: index < 4
                            color: root.separator
                        }
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 50
            radius: 17
            antialiasing: true
            scale: reconnectHover.pressed ? 0.995 : 1
            color: root.glassInteractive
            border.width: 1
            border.color: root.glassStroke
            opacity: root.wifi.busy || !root.wifi.currentNetwork ? 0.50 : 1

            Behavior on scale { NumberAnimation { duration: 115; easing.type: Easing.OutCubic } }

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.018) }
                    GradientStop { position: 0.66; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.030) }
                }
            }

            Rectangle {
                id: reconnectHoverPlane
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                color: chrome.theme.alpha(chrome.accent, 0.065)
                opacity: reconnectHover.containsMouse ? 1 : 0

                Behavior on opacity {
                    NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
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
                color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.06), 0.34)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.foreground, 0.035)

                Text {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -1
                    text: "󰑐"
                    color: chrome.theme.alpha(chrome.textSecondary, 0.80)
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 15
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    renderType: Text.NativeRendering
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 55
                anchors.verticalCenter: parent.verticalCenter
                text: root.wifi.activeAction === "reconnect" ? "Reconnecting…" : "Reconnect"
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }

            MouseArea {
                id: reconnectHover
                anchors.fill: parent
                enabled: !root.wifi.busy && root.wifi.currentNetwork !== null
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.wifi.reconnect()
            }
        }

        Rectangle {
            width: parent.width
            height: 50
            radius: 17
            antialiasing: true
            scale: disconnectHover.pressed ? 0.995 : 1
            color: root.glassInteractive
            border.width: 1
            border.color: root.glassStroke
            opacity: root.wifi.busy ? 0.50 : 1

            Behavior on scale { NumberAnimation { duration: 115; easing.type: Easing.OutCubic } }

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.018) }
                    GradientStop { position: 0.66; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.030) }
                }
            }

            Rectangle {
                id: disconnectHoverPlane
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                color: chrome.theme.alpha(chrome.accent, 0.065)
                opacity: disconnectHover.containsMouse ? 1 : 0

                Behavior on opacity {
                    NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
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
                color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.06), 0.34)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.foreground, 0.035)

                MahoWifiGlyph {
                    anchors.centerIn: parent
                    width: 17
                    height: 17
                    disabled: true
                    glyphColor: chrome.theme.alpha(chrome.textSecondary, 0.80)
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 55
                anchors.verticalCenter: parent.verticalCenter
                text: root.wifi.activeAction === "disconnect" ? "Disconnecting…" : "Disconnect"
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }

            MouseArea {
                id: disconnectHover
                anchors.fill: parent
                enabled: !root.wifi.busy
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.wifi.disconnect()
            }
        }
    }
}
