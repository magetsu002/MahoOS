import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi
    required property var network
    signal backRequested()

    property string password: passwordInput.text

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

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 14

        Rectangle {
            width: parent.width
            height: 86
            radius: 19
            antialiasing: true
            color: root.glassRaised
            border.width: 1
            border.color: root.glassStroke

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.038) }
                    GradientStop { position: 0.34; color: chrome.theme.alpha(chrome.accent, 0.034) }
                    GradientStop { position: 0.74; color: "transparent" }
                    GradientStop { position: 1; color: chrome.theme.alpha(chrome.accent, 0.016) }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                width: 50
                height: 50
                radius: 17
                antialiasing: true
                color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.12), 0.45)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.070)

                Text {
                    anchors.centerIn: parent
                    text: "󰖩"
                    color: chrome.theme.alpha(chrome.accent, 0.90)
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 23
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 80
                anchors.right: parent.right
                anchors.rightMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4

                Text {
                    width: parent.width
                    text: String(root.network.ssid || "Wi-Fi")
                    color: chrome.textPrimary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Secured network"
                    color: chrome.theme.alpha(chrome.textSecondary, 0.66)
                    font.family: "Inter"
                    font.pixelSize: 10
                }
            }
        }

        Text {
            width: parent.width
            text: "Enter the network password. It is sent to NetworkManager over stdin and is not placed in the process arguments."
            wrapMode: Text.WordWrap
            color: chrome.theme.alpha(chrome.textSecondary, 0.68)
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
            border.color: passwordInput.activeFocus
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
                id: passwordInput
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
                focus: true
                Keys.onReturnPressed: {
                    if (text.length > 0 && !root.wifi.busy)
                        root.wifi.connectNetwork(root.network.ssid, text, false)
                }
            }

            Text {
                visible: passwordInput.text.length === 0 && !passwordInput.activeFocus
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                text: "Password"
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
                enabled: passwordInput.text.length > 0 && !root.wifi.busy
                onClicked: root.wifi.connectNetwork(root.network.ssid, passwordInput.text, false)
            }
        }
    }
}
