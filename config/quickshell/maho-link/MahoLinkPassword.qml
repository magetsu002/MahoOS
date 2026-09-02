import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi
    required property var network
    signal backRequested()

    property string password: passwordInput.text

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 16

        Text {
            text: String(root.network.ssid || "Wi-Fi")
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 20
            font.weight: Font.DemiBold
        }

        Text {
            width: parent.width
            text: "Enter the network password. It is sent to NetworkManager over stdin and is not placed in the process arguments."
            wrapMode: Text.WordWrap
            color: chrome.textSecondary
            font.family: "Inter"
            font.pixelSize: 12
            lineHeight: 1.25
        }

        Rectangle {
            width: parent.width
            height: 49
            radius: 14
            color: chrome.theme.alpha(chrome.insetColor, 0.78)
            border.width: 1
            border.color: passwordInput.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.58)
                : chrome.theme.alpha(chrome.theme.outline, 0.16)

            TextInput {
                id: passwordInput
                anchors.fill: parent
                anchors.leftMargin: 15
                anchors.rightMargin: 15
                verticalAlignment: TextInput.AlignVCenter
                echoMode: TextInput.Password
                passwordCharacter: "•"
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.45)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 14
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
                color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                font.family: "Inter"
                font.pixelSize: 14
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
