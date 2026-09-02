import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi
    signal backRequested()

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 14

        Text {
            text: "Other Network"
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 20
            font.weight: Font.DemiBold
        }

        Text {
            width: parent.width
            text: "Join a hidden personal or open Wi-Fi network. Enterprise profiles remain outside this milestone."
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
            border.color: ssidInput.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.58)
                : chrome.theme.alpha(chrome.theme.outline, 0.16)

            TextInput {
                id: ssidInput
                anchors.fill: parent
                anchors.leftMargin: 15
                anchors.rightMargin: 15
                verticalAlignment: TextInput.AlignVCenter
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.45)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 14
                focus: true
            }

            Text {
                visible: ssidInput.text.length === 0 && !ssidInput.activeFocus
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                text: "Network name"
                color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                font.family: "Inter"
                font.pixelSize: 14
            }
        }

        Rectangle {
            width: parent.width
            height: 49
            radius: 14
            color: chrome.theme.alpha(chrome.insetColor, 0.78)
            border.width: 1
            border.color: hiddenPassword.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.58)
                : chrome.theme.alpha(chrome.theme.outline, 0.16)

            TextInput {
                id: hiddenPassword
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
            }

            Text {
                visible: hiddenPassword.text.length === 0 && !hiddenPassword.activeFocus
                anchors.left: parent.left
                anchors.leftMargin: 15
                anchors.verticalCenter: parent.verticalCenter
                text: "Password (leave empty for open network)"
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
                enabled: ssidInput.text.trim().length > 0 && !root.wifi.busy
                onClicked: root.wifi.connectNetwork(ssidInput.text.trim(), hiddenPassword.text, true)
            }
        }
    }
}
