import QtQuick

Item {
    id: root
    required property var chrome
    required property var wifi

    signal networkSelected(var network)
    signal detailsRequested(var network)
    signal manualRequested()

    readonly property int networkCount:
        root.wifi.wifiEnabled && root.wifi.networks ? root.wifi.networks.length : 0
    readonly property bool emptyState: networkCount === 0

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 13

        Rectangle {
            id: currentCard
            width: parent.width
            height: 96
            radius: 18
            readonly property var currentNetwork: root.wifi.currentNetwork
            color: currentNetwork
                ? chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.accent, 0.11), 0.97)
                : chrome.theme.alpha(chrome.insetColor, 0.94)
            border.width: 1
            border.color: currentNetwork
                ? chrome.theme.alpha(chrome.accent, 0.12)
                : chrome.theme.alpha(chrome.theme.outline, 0.08)

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
            height: Math.max(root.emptyState ? 176 : 144, root.height - 151)
            radius: 18
            color: chrome.theme.alpha(chrome.mix(chrome.insetColor, chrome.theme.background, 0.10), 0.96)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.07)
            clip: true

            ListView {
                id: networksList
                anchors.fill: parent
                anchors.topMargin: 4
                anchors.bottomMargin: 58
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
                        color: chrome.theme.alpha(chrome.theme.outline, 0.065)
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 54, 330)
                    spacing: 7
                    visible: networksList.count === 0

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: !root.wifi.available ? "NetworkManager unavailable"
                            : !root.wifi.wifiEnabled ? "Wi-Fi is turned off"
                            : !root.wifi.snapshotReady ? "Scanning…"
                            : root.wifi.currentNetwork ? "No other networks found" : "No networks found"
                        color: chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.WordWrap
                        visible: root.wifi.available && root.wifi.wifiEnabled && root.wifi.snapshotReady
                        text: root.wifi.currentNetwork
                            ? "You’re connected. Refresh to scan for nearby networks again."
                            : "Refresh the scan or move closer to a wireless network."
                        color: chrome.theme.alpha(chrome.textSecondary, 0.72)
                        font.family: "Inter"
                        font.pixelSize: 10
                        lineHeight: 1.25
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: otherRow.top
                height: 1
                color: chrome.theme.alpha(chrome.theme.outline, 0.07)
            }

            Item {
                id: otherRow
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 54

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 3
                    radius: 13
                    color: otherHover.containsMouse ? chrome.theme.alpha(chrome.accent, 0.05) : "transparent"
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: 17
                    anchors.verticalCenter: parent.verticalCenter
                    width: 27
                    height: 27
                    radius: 14
                    color: chrome.theme.alpha(chrome.textSecondary, 0.10)
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
                    color: chrome.theme.alpha(chrome.textSecondary, 0.84)
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
