import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi
    required property var network
    signal backRequested()

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 14

        Row {
            width: parent.width
            spacing: 12

            Rectangle {
                width: 46
                height: 46
                radius: 15
                color: chrome.theme.alpha(chrome.accent, 0.14)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.22)

                Text {
                    anchors.centerIn: parent
                    text: "󰖩"
                    color: chrome.accent
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 21
                }
            }

            Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    text: String(root.network.ssid || "Wi-Fi")
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 19
                    font.weight: Font.DemiBold
                }
                Text {
                    text: "Connected · " + String(root.network.quality || "")
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 12
                }
            }
        }

        Rectangle {
            width: parent.width
            height: detailsColumn.implicitHeight + 28
            radius: 16
            color: chrome.theme.alpha(chrome.insetColor, 0.70)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.14)

            Column {
                id: detailsColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 14
                spacing: 12

                Repeater {
                    model: [
                        ["Signal", String(root.network.signal || 0) + "%"],
                        ["Security", String(root.network.security || "Unknown")],
                        ["Band", String(root.network.band || "Unknown")],
                        ["IPv4", String(root.network.ipv4 || "Unavailable")],
                        ["Router", String(root.network.gateway || "Unavailable")]
                    ]

                    Item {
                        width: detailsColumn.width
                        height: 19
                        Text {
                            anchors.left: parent.left
                            text: modelData[0]
                            color: chrome.textSecondary
                            font.family: "Inter"
                            font.pixelSize: 12
                        }
                        Text {
                            anchors.right: parent.right
                            width: parent.width * 0.62
                            horizontalAlignment: Text.AlignRight
                            elide: Text.ElideMiddle
                            text: modelData[1]
                            color: chrome.textPrimary
                            font.family: "Inter"
                            font.pixelSize: 12
                            font.weight: Font.Medium
                        }
                    }
                }
            }
        }

        MahoLinkButton {
            width: parent.width
            chrome: root.chrome
            label: root.wifi.busy ? "Disconnecting…" : "Disconnect"
            destructive: true
            enabled: !root.wifi.busy
            onClicked: root.wifi.disconnect()
        }
    }
}
