import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi

    signal networkSelected(var network)
    signal detailsRequested(var network)
    signal manualRequested()

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 13

        Rectangle {
            id: currentCard
            width: parent.width
            height: 98
            radius: 18
            readonly property var currentNetwork: root.wifi.currentNetwork
            color: chrome.theme.alpha(currentNetwork ? chrome.accent : chrome.insetColor, currentNetwork ? 0.13 : 0.72)
            border.width: 1
            border.color: currentNetwork
                ? chrome.theme.alpha(chrome.accent, 0.22)
                : chrome.theme.alpha(chrome.theme.outline, 0.15)

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 19
                anchors.verticalCenter: parent.verticalCenter
                text: currentCard.currentNetwork ? "󰖩" : "󰖪"
                color: currentCard.currentNetwork ? chrome.accent : chrome.textSecondary
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 28
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 67
                anchors.right: signalGroup.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4

                Text {
                    width: parent.width
                    text: currentCard.currentNetwork
                        ? String(currentCard.currentNetwork.ssid || "Wi-Fi")
                        : root.wifi.wifiEnabled ? "Not Connected" : "Wi-Fi Off"
                    color: chrome.textPrimary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }
                Text {
                    width: parent.width
                    text: currentCard.currentNetwork
                        ? "Connected · " + String(currentCard.currentNetwork.quality || "")
                        : root.wifi.available
                            ? (root.wifi.wifiEnabled ? "Choose a network below" : "Enable Wi-Fi to scan")
                            : "NetworkManager unavailable"
                    color: chrome.textSecondary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 12
                }
            }

            Row {
                id: signalGroup
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                visible: currentCard.currentNetwork !== null

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: Boolean(currentCard.currentNetwork && currentCard.currentNetwork.secured)
                    text: ""
                    color: chrome.textSecondary
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 12
                }
                MahoLinkSignal {
                    anchors.verticalCenter: parent.verticalCenter
                    chrome: root.chrome
                    strength: Number(currentCard.currentNetwork ? currentCard.currentNetwork.signal : 0)
                }
            }

            MouseArea {
                anchors.fill: parent
                enabled: currentCard.currentNetwork !== null
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.detailsRequested(currentCard.currentNetwork)
            }
        }

        Item {
            width: parent.width
            height: 29

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "Available Networks"
                color: chrome.textSecondary
                font.family: "Inter"
                font.pixelSize: 12
                font.weight: Font.Medium
            }

            Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: root.wifi.busy ? "Scanning…" : "Refresh"
                color: root.wifi.wifiEnabled ? chrome.accent : chrome.theme.alpha(chrome.textSecondary, 0.40)
                font.family: "Inter"
                font.pixelSize: 11

                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -8
                    enabled: root.wifi.wifiEnabled && !root.wifi.busy
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.wifi.rescan()
                }
            }
        }

        Rectangle {
            width: parent.width
            height: Math.max(144, root.height - 153)
            radius: 18
            color: chrome.theme.alpha(chrome.insetColor, 0.67)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.14)
            clip: true

            ListView {
                id: networksList
                anchors.fill: parent
                anchors.topMargin: 4
                anchors.bottomMargin: 60
                clip: true
                model: root.wifi.wifiEnabled ? root.wifi.networks : []
                boundsBehavior: Flickable.StopAtBounds

                delegate: Item {
                    required property var modelData
                    width: networksList.width
                    height: 61

                    MahoLinkNetworkRow {
                        anchors.fill: parent
                        chrome: root.chrome
                        network: modelData
                        interactionEnabled: !root.wifi.busy
                        onSelected: root.networkSelected(modelData)
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 53
                        anchors.right: parent.right
                        anchors.rightMargin: 14
                        anchors.bottom: parent.bottom
                        height: 1
                        color: chrome.theme.alpha(chrome.theme.outline, 0.10)
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: networksList.count === 0
                    text: !root.wifi.available ? "NetworkManager unavailable"
                        : !root.wifi.wifiEnabled ? "Wi-Fi is turned off"
                        : root.wifi.snapshotReady ? "No networks found" : "Scanning…"
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 12
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: otherRow.top
                height: 1
                color: chrome.theme.alpha(chrome.theme.outline, 0.12)
            }

            Item {
                id: otherRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 56

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 3
                    radius: 13
                    color: otherHover.containsMouse ? chrome.theme.alpha(chrome.accent, 0.07) : "transparent"
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: 17
                    anchors.verticalCenter: parent.verticalCenter
                    width: 27
                    height: 27
                    radius: 14
                    color: chrome.theme.alpha(chrome.textSecondary, 0.12)
                    Text {
                        anchors.centerIn: parent
                        text: "+"
                        color: chrome.textSecondary
                        font.family: "Inter"
                        font.pixelSize: 18
                    }
                }

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 57
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Other Network…"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 14
                    font.weight: Font.Medium
                }

                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 17
                    anchors.verticalCenter: parent.verticalCenter
                    text: "›"
                    color: chrome.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 20
                }

                MouseArea {
                    id: otherHover
                    anchors.fill: parent
                    enabled: root.wifi.wifiEnabled && !root.wifi.busy
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.manualRequested()
                }
            }
        }
    }
}
