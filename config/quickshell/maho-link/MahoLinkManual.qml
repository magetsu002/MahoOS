import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi
    signal backRequested()

    readonly property color glassLow: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.64),
        0.42
    )
    readonly property color glassInteractive: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56),
        0.47
    )
    readonly property color glassStroke: chrome.theme.alpha(chrome.theme.foreground, 0.055)
    readonly property color glassHighlight: chrome.theme.alpha(chrome.theme.foreground, 0.050)

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 14

        Rectangle {
            width: parent.width
            height: 78
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
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.024) }
                    GradientStop { position: 0.58; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.060) }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                width: 46
                height: 46
                radius: 16
                antialiasing: true
                color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.08), 0.40)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.foreground, 0.040)

                Text {
                    anchors.centerIn: parent
                    text: "+"
                    color: chrome.theme.alpha(chrome.accent, 0.86)
                    font.family: "Inter"
                    font.pixelSize: 24
                    font.weight: Font.Light
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 76
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 3

                Text {
                    text: "Other Network"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: "Join a hidden personal or open Wi-Fi network."
                    color: chrome.theme.alpha(chrome.textSecondary, 0.64)
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 10
                }
            }
        }

        Text {
            width: parent.width
            text: "Enterprise profiles remain outside this milestone."
            wrapMode: Text.WordWrap
            color: chrome.theme.alpha(chrome.textSecondary, 0.62)
            font.family: "Inter"
            font.pixelSize: 10
            lineHeight: 1.25
        }

        Rectangle {
            width: parent.width
            height: 50
            radius: 16
            antialiasing: true
            color: root.glassInteractive
            border.width: 1
            border.color: ssidInput.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.22)
                : root.glassStroke

            Behavior on border.color { ColorAnimation { duration: 120 } }

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.022) }
                    GradientStop { position: 0.64; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.028) }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.top: parent.top
                height: 1
                radius: 1
                antialiasing: true
                color: root.glassHighlight
            }

            TextInput {
                id: ssidInput
                anchors.fill: parent
                anchors.leftMargin: 15
                anchors.rightMargin: 15
                verticalAlignment: TextInput.AlignVCenter
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.36)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 13
                focus: true
            }

            Text {
                visible: ssidInput.text.length === 0 && !ssidInput.activeFocus
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                text: "Network name"
                color: chrome.theme.alpha(chrome.textSecondary, 0.60)
                font.family: "Inter"
                font.pixelSize: 13
            }
        }

        Rectangle {
            width: parent.width
            height: 50
            radius: 16
            antialiasing: true
            color: root.glassInteractive
            border.width: 1
            border.color: hiddenPassword.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.22)
                : root.glassStroke

            Behavior on border.color { ColorAnimation { duration: 120 } }

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.022) }
                    GradientStop { position: 0.64; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.028) }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.top: parent.top
                height: 1
                radius: 1
                antialiasing: true
                color: root.glassHighlight
            }

            TextInput {
                id: hiddenPassword
                anchors.fill: parent
                anchors.leftMargin: 15
                anchors.rightMargin: 15
                verticalAlignment: TextInput.AlignVCenter
                echoMode: TextInput.Password
                passwordCharacter: "•"
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.36)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 13
            }

            Text {
                visible: hiddenPassword.text.length === 0 && !hiddenPassword.activeFocus
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                text: "Password (leave empty for open network)"
                color: chrome.theme.alpha(chrome.textSecondary, 0.60)
                font.family: "Inter"
                font.pixelSize: 13
            }
        }

        Row {
            width: parent.width
            spacing: 10

            MahoLinkButton {
                width: (parent.width - 10) / 2
                chrome: root.chrome
                label: "Cancel"
                onClicked: root.backRequested()
            }

            MahoLinkButton {
                width: (parent.width - 10) / 2
                chrome: root.chrome
                label: root.wifi.busy ? "Connecting…" : "Connect"
                primary: true
                enabled: ssidInput.text.trim().length > 0 && !root.wifi.busy
                onClicked: root.wifi.connectNetwork(ssidInput.text.trim(), hiddenPassword.text, true)
            }
        }
    }
}
