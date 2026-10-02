import QtQuick

Item {
    id: root

    required property var chrome
    required property var bluetooth
    required property var device

    signal cancelRequested()
    signal confirmed()

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 54, 350)
        spacing: 16

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 82
            height: 82
            radius: 41
            color: chrome.theme.alpha(chrome.theme.error, 0.09)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.error, 0.12)

            Text {
                anchors.centerIn: parent
                text: "󰆴"
                color: chrome.theme.error
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 30
            }
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Forget " + String(device && device.name ? device.name : "this device") + "?"
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 18
            font.weight: Font.DemiBold
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "This device will be removed from your paired devices and you’ll need to pair it again to use it."
            color: chrome.theme.alpha(chrome.textSecondary, 0.78)
            font.family: "Inter"
            font.pixelSize: 11
            lineHeight: 1.28
        }

        Rectangle {
            width: parent.width
            height: 46
            radius: 14
            color: confirmHover.containsMouse || confirmHover.activeFocus
                ? chrome.theme.alpha(chrome.theme.error, 0.28)
                : chrome.theme.alpha(chrome.theme.error, 0.21)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.error, 0.24)
            opacity: root.bluetooth.busy ? 0.55 : 1

            Text {
                anchors.centerIn: parent
                text: root.bluetooth.activeAction === "forget" ? "Forgetting…" : "Forget Device"
                color: chrome.theme.error
                font.family: "Inter"
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            MouseArea {
                id: confirmHover
                anchors.fill: parent
                enabled: !root.bluetooth.busy
                hoverEnabled: true
                activeFocusOnTab: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.confirmed()
                Keys.onReturnPressed: root.confirmed()
                Keys.onSpacePressed: root.confirmed()
            }
        }

        Rectangle {
            width: parent.width
            height: 44
            radius: 14
            color: cancelHover.containsMouse || cancelHover.activeFocus
                ? chrome.theme.alpha(chrome.textSecondary, 0.12)
                : chrome.theme.alpha(chrome.textSecondary, 0.075)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.07)

            Text {
                anchors.centerIn: parent
                text: "Cancel"
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            MouseArea {
                id: cancelHover
                anchors.fill: parent
                hoverEnabled: true
                activeFocusOnTab: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.cancelRequested()
                Keys.onReturnPressed: root.cancelRequested()
                Keys.onSpacePressed: root.cancelRequested()
            }
        }
    }
}
