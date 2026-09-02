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

    // Mirror the proven Bluetooth material tiers so Wi-Fi feels like the same
    // native surface instead of a separate opaque settings panel.
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
    readonly property color glassLowlight: chrome.theme.alpha(chrome.theme.background, 0.085)
    readonly property color separator: chrome.theme.alpha(chrome.theme.foreground, 0.028)

    anchors.fill: parent

    Column {
        anchors.fill: parent
        spacing: 13

        Rectangle {
            id: currentCard
            width: parent.width
            height: 102
            radius: 20
            antialiasing: true
            scale: currentHover.pressed && currentNetwork ? 0.997 : 1
            readonly property var currentNetwork: root.wifi.currentNetwork
            color: currentHover.containsMouse && currentNetwork
                ? chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.035), 0.59)
                : root.glassRaised
            border.width: 1
            border.color: currentHover.containsMouse && currentNetwork
                ? chrome.theme.alpha(chrome.accent, 0.11)
                : root.glassStroke

            Behavior on color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
            Behavior on border.color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
            Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                gradient: Gradient {
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.040) }
                    GradientStop {
                        position: 0.30
                        color: chrome.theme.alpha(currentCard.currentNetwork ? chrome.accent : chrome.theme.background, currentCard.currentNetwork ? 0.040 : 0.018)
                    }
                    GradientStop { position: 0.72; color: "transparent" }
                    GradientStop {
                        position: 1
                        color: chrome.theme.alpha(currentCard.currentNetwork ? chrome.accent : chrome.theme.background, 0.018)
                    }
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
                id: currentIcon
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                width: 56
                height: 56
                radius: 19
                antialiasing: true
                scale: currentHover.containsMouse && currentCard.currentNetwork ? 1.012 : 1
                color: chrome.theme.alpha(
                    chrome.mix(
                        chrome.theme.surfaceHigh,
                        currentCard.currentNetwork ? chrome.accent : chrome.theme.background,
                        currentCard.currentNetwork ? 0.12 : 0.20
                    ),
                    0.47
                )
                border.width: 1
                border.color: chrome.theme.alpha(
                    currentCard.currentNetwork ? chrome.accent : chrome.theme.foreground,
                    currentCard.currentNetwork ? 0.09 : 0.045
                )

                Behavior on scale { NumberAnimation { duration: 135; easing.type: Easing.OutCubic } }

                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    antialiasing: true
                    gradient: Gradient {
                        GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.045) }
                        GradientStop { position: 0.58; color: "transparent" }
                        GradientStop {
                            position: 1
                            color: chrome.theme.alpha(currentCard.currentNetwork ? chrome.accent : chrome.theme.background, 0.035)
                        }
                    }
                }

                MahoWifiGlyph {
                    anchors.centerIn: parent
                    width: 29
                    height: 29
                    disabled: !currentCard.currentNetwork
                    glyphColor: currentCard.currentNetwork
                        ? chrome.theme.alpha(chrome.accent, 0.92)
                        : chrome.theme.alpha(chrome.textSecondary, 0.82)
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 88
                anchors.right: signalGroup.left
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5

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
                    color: currentCard.currentNetwork
                        ? chrome.theme.alpha(chrome.accent, 0.78)
                        : chrome.theme.alpha(chrome.textSecondary, 0.70)
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 11
                    font.weight: currentCard.currentNetwork ? Font.Medium : Font.Normal
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
                    anchors.verticalCenterOffset: -1
                    visible: Boolean(currentCard.currentNetwork && currentCard.currentNetwork.secured)
                    text: ""
                    color: chrome.theme.alpha(chrome.textSecondary, 0.74)
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 11
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    renderType: Text.NativeRendering
                }
                MahoLinkSignal {
                    anchors.verticalCenter: parent.verticalCenter
                    chrome: root.chrome
                    strength: Number(currentCard.currentNetwork ? currentCard.currentNetwork.signal : 0)
                }
            }

            MouseArea {
                id: currentHover
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
                color: chrome.theme.alpha(chrome.textSecondary, 0.78)
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }

            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 7

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    antialiasing: true
                    visible: root.wifi.busy
                    color: chrome.accent
                    opacity: 0.72

                    SequentialAnimation on opacity {
                        running: root.wifi.busy
                        loops: Animation.Infinite
                        NumberAnimation { to: 0.26; duration: 620; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 0.82; duration: 620; easing.type: Easing.InOutSine }
                    }
                }

                Text {
                    text: root.wifi.busy ? "Scanning…" : "Refresh"
                    color: root.wifi.wifiEnabled
                        ? chrome.theme.alpha(chrome.accent, 0.90)
                        : chrome.theme.alpha(chrome.textSecondary, 0.40)
                    font.family: "Inter"
                    font.pixelSize: 10
                    font.weight: Font.Medium

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
        }

        Rectangle {
            id: networksCard
            width: parent.width
            height: Math.max(root.emptyState ? 176 : 144, root.height - 157)
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
                    GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.022) }
                    GradientStop { position: 0.58; color: "transparent" }
                    GradientStop { position: 1; color: root.glassLowlight }
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
                    height: 58

                    MahoLinkNetworkRow {
                        anchors.fill: parent
                        chrome: root.chrome
                        network: modelData
                        interactionEnabled: !root.wifi.busy
                        onSelected: root.networkSelected(modelData)
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.leftMargin: 61
                        anchors.right: parent.right
                        anchors.rightMargin: 18
                        anchors.bottom: parent.bottom
                        height: 1
                        color: root.separator
                    }
                }

                Column {
                    anchors.centerIn: parent
                    width: Math.min(parent.width - 54, 330)
                    spacing: 7
                    visible: networksList.count === 0

                    Item {
                        id: scanRing
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 42
                        height: 42

                        Repeater {
                            model: 16
                            Rectangle {
                                required property int index
                                readonly property real angle: index * Math.PI * 2 / 16
                                width: 2
                                height: 2
                                radius: 1
                                antialiasing: true
                                x: scanRing.width / 2 + Math.cos(angle) * 18 - width / 2
                                y: scanRing.height / 2 + Math.sin(angle) * 18 - height / 2
                                color: chrome.theme.alpha(
                                    root.wifi.busy ? chrome.accent : chrome.textSecondary,
                                    0.50
                                )
                                opacity: root.wifi.busy
                                    ? 0.28 + ((index % 4) * 0.15)
                                    : 0.48
                            }
                        }

                        MahoWifiGlyph {
                            anchors.centerIn: parent
                            width: 20
                            height: 20
                            disabled: !root.wifi.wifiEnabled
                            glyphColor: chrome.theme.alpha(
                                root.wifi.busy ? chrome.accent : chrome.textSecondary,
                                root.wifi.busy ? 0.82 : 0.56
                            )
                        }
                    }

                    Text {
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: !root.wifi.available ? "NetworkManager unavailable"
                            : !root.wifi.wifiEnabled ? "Wi-Fi is turned off"
                            : !root.wifi.snapshotReady ? "Scanning…"
                            : root.wifi.currentNetwork ? "No other networks found" : "No networks found"
                        color: chrome.theme.alpha(chrome.textPrimary, 0.88)
                        font.family: "Inter"
                        font.pixelSize: 11
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
                        color: chrome.theme.alpha(chrome.textSecondary, 0.60)
                        font.family: "Inter"
                        font.pixelSize: 9
                        lineHeight: 1.25
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                anchors.bottom: otherRow.top
                height: 1
                color: root.separator
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
                    radius: 15
                    antialiasing: true
                    scale: otherHover.pressed ? 0.996 : 1
                    color: otherHover.pressed
                        ? chrome.theme.alpha(chrome.theme.foreground, 0.050)
                        : otherHover.containsMouse
                            ? chrome.theme.alpha(chrome.theme.foreground, 0.026)
                            : "transparent"
                    Behavior on color { ColorAnimation { duration: 125; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    width: 30
                    height: 30
                    radius: 11
                    antialiasing: true
                    color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.08), 0.36)
                    border.width: 1
                    border.color: chrome.theme.alpha(chrome.theme.foreground, 0.038)

                    Text {
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: -1
                        text: "+"
                        color: chrome.theme.alpha(chrome.accent, 0.86)
                        font.family: "Inter"
                        font.pixelSize: 18
                        font.weight: Font.Light
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        renderType: Text.NativeRendering
                    }
                }

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 56
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Other Network…"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 12
                    font.weight: Font.Medium
                }

                Text {
                    anchors.right: parent.right
                    anchors.rightMargin: 16
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.verticalCenterOffset: -1
                    text: "›"
                    color: otherHover.containsMouse
                        ? chrome.theme.alpha(chrome.textPrimary, 0.78)
                        : chrome.theme.alpha(chrome.textSecondary, 0.58)
                    font.family: "Inter"
                    font.pixelSize: 20
                    font.weight: Font.Light
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    renderType: Text.NativeRendering
                }

                MouseArea {
                    id: otherHover
                    anchors.fill: parent
                    enabled: root.wifi.wifiEnabled && !root.wifi.busy
                    hoverEnabled: true
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.manualRequested()
                }
            }
        }
    }
}
