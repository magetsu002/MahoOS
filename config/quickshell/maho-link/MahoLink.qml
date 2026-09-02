import QtQuick

Item {
    id: root

    required property var theme
    required property var wifi
    required property real availableHeight
    property bool shown: false
    property string page: "main"
    property var selectedNetwork: null

    signal closeRequested()

    width: 486
    height: Math.min(652, Math.max(500, availableHeight - 40))
    focus: shown
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.988
    transform: Translate {
        y: root.shown ? 0 : -10
        Behavior on y { NumberAnimation { duration: root.shown ? 210 : 150; easing.type: Easing.OutCubic } }
    }

    Behavior on opacity { NumberAnimation { duration: shown ? 210 : 150; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: shown ? 210 : 150; easing.type: Easing.OutCubic } }

    readonly property color textPrimary: theme.foreground
    readonly property color textSecondary: theme.alpha(theme.muted, 0.78)
    readonly property color insetColor: mix(theme.surfaceHigh, theme.background, 0.30)
    readonly property color accent: stableAccent(theme.primary)

    function mix(a, b, amount) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            a.r * (1 - t) + b.r * t,
            a.g * (1 - t) + b.g * t,
            a.b * (1 - t) + b.b * t,
            a.a * (1 - t) + b.a * t
        )
    }

    function stableAccent(source) {
        const saturation = source.hsvSaturation
        if (saturation < 0.08)
            return mix(theme.foreground, theme.surfaceHigh, 0.38)
        const hue = source.hsvHue < 0 ? 0 : source.hsvHue
        return Qt.hsva(
            hue,
            Math.max(0.20, Math.min(0.62, saturation)),
            Math.max(0.62, Math.min(0.88, source.hsvValue)),
            1
        )
    }

    function goBack() {
        if (page === "main") {
            closeRequested()
            return
        }
        page = "main"
        selectedNetwork = null
    }

    function selectNetwork(network) {
        wifi.errorText = ""
        wifi.actionMessage = ""
        if (network.enterprise) {
            wifi.errorText = "Enterprise Wi-Fi needs an existing NetworkManager profile in this milestone."
            return
        }
        if (network.secured) {
            selectedNetwork = network
            page = "password"
            return
        }
        wifi.connectNetwork(network.ssid, "", false)
    }

    Keys.onEscapePressed: root.closeRequested()

    Connections {
        target: root.wifi
        function onActionMessageChanged() {
            if (root.wifi.actionMessage === "")
                return
            if (root.page !== "main") {
                root.page = "main"
                root.selectedNetwork = null
            }
        }
        function onWifiEnabledChanged() {
            if (!root.wifi.wifiEnabled && root.page !== "main")
                root.goBack()
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -7
        radius: 28
        color: theme.alpha(root.accent, 0.055)
        border.width: 1
        border.color: theme.alpha(root.accent, 0.07)
        opacity: 0.86
    }

    Rectangle {
        id: material
        anchors.fill: parent
        radius: 24
        color: theme.alpha(root.mix(theme.surfaceHigh, theme.background, 0.20), 0.935)
        border.width: 1
        border.color: theme.alpha(theme.outline, 0.25)
        clip: true

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 180
            color: theme.alpha(root.accent, 0.055)
            gradient: Gradient {
                GradientStop { position: 0; color: theme.alpha(root.accent, 0.085) }
                GradientStop { position: 1; color: "transparent" }
            }
        }
    }

    // Consume clicks inside the material so the full-screen outside catcher does not close it.
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: function(mouse) { mouse.accepted = true }
    }

    Item {
        id: header
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 19
        anchors.rightMargin: 19
        anchors.topMargin: 18
        height: 42

        Rectangle {
            id: backButton
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 36
            height: 36
            radius: 12
            color: backHover.containsMouse ? theme.alpha(root.accent, 0.10) : "transparent"

            Text {
                anchors.centerIn: parent
                text: "‹"
                color: root.textPrimary
                font.family: "Inter"
                font.pixelSize: 30
                font.weight: Font.Light
                y: -1
            }

            MouseArea {
                id: backHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.goBack()
            }
        }

        Text {
            anchors.centerIn: parent
            text: root.page === "main" ? "Wi-Fi"
                : root.page === "password" ? "Join Network"
                : root.page === "manual" ? "Other Network"
                : "Network Details"
            color: root.textPrimary
            font.family: "Inter"
            font.pixelSize: 18
            font.weight: Font.DemiBold
        }

        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            Rectangle {
                visible: root.page === "main"
                width: 48
                height: 28
                radius: 14
                color: root.wifi.wifiEnabled
                    ? theme.alpha(root.accent, toggleHover.containsMouse ? 0.95 : 0.86)
                    : theme.alpha(root.textSecondary, 0.18)
                border.width: 1
                border.color: root.wifi.wifiEnabled
                    ? theme.alpha(root.accent, 0.48)
                    : theme.alpha(theme.outline, 0.20)
                opacity: root.wifi.available && !root.wifi.busy ? 1 : 0.48

                Rectangle {
                    width: 22
                    height: 22
                    radius: 11
                    y: 3
                    x: root.wifi.wifiEnabled ? parent.width - width - 3 : 3
                    color: Qt.rgba(1, 1, 1, 0.94)
                    Behavior on x { NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
                }

                MouseArea {
                    id: toggleHover
                    anchors.fill: parent
                    enabled: root.wifi.available && !root.wifi.busy
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.wifi.setWifiEnabled(!root.wifi.wifiEnabled)
                }
            }

            Rectangle {
                width: 32
                height: 32
                radius: 11
                color: closeHover.containsMouse ? theme.alpha(root.textSecondary, 0.10) : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: root.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 21
                }

                MouseArea {
                    id: closeHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.closeRequested()
                }
            }
        }
    }

    Item {
        id: body
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 19
        anchors.rightMargin: 19
        anchors.topMargin: 12
        anchors.bottomMargin: 18

        Item {
            id: mainPage
            anchors.fill: parent
            visible: root.page === "main"

            Column {
                anchors.fill: parent
                spacing: 13

                Rectangle {
                    width: parent.width
                    height: 98
                    radius: 18
                    color: theme.alpha(root.currentNetwork ? root.accent : root.insetColor, root.currentNetwork ? 0.13 : 0.72)
                    border.width: 1
                    border.color: root.currentNetwork
                        ? theme.alpha(root.accent, 0.22)
                        : theme.alpha(theme.outline, 0.15)

                    readonly property var currentNetwork: root.wifi.currentNetwork

                    Text {
                        anchors.left: parent.left
                        anchors.leftMargin: 19
                        anchors.verticalCenter: parent.verticalCenter
                        text: parent.currentNetwork ? "󰖩" : (root.wifi.wifiEnabled ? "󰖪" : "󰖪")
                        color: parent.currentNetwork ? root.accent : root.textSecondary
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
                            text: mainPage.parent.currentNetwork
                                ? String(mainPage.parent.currentNetwork.ssid || "Wi-Fi")
                                : root.wifi.wifiEnabled ? "Not Connected" : "Wi-Fi Off"
                            color: root.textPrimary
                            elide: Text.ElideRight
                            font.family: "Inter"
                            font.pixelSize: 17
                            font.weight: Font.DemiBold
                        }
                        Text {
                            width: parent.width
                            text: mainPage.parent.currentNetwork
                                ? "Connected · " + String(mainPage.parent.currentNetwork.quality || "")
                                : root.wifi.available
                                    ? (root.wifi.wifiEnabled ? "Choose a network below" : "Enable Wi-Fi to scan")
                                    : "NetworkManager unavailable"
                            color: root.textSecondary
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
                        visible: parent.currentNetwork !== null

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: Boolean(mainPage.parent.currentNetwork && mainPage.parent.currentNetwork.secured)
                            text: ""
                            color: root.textSecondary
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 12
                        }
                        MahoLinkSignal {
                            anchors.verticalCenter: parent.verticalCenter
                            chrome: root
                            strength: Number(mainPage.parent.currentNetwork ? mainPage.parent.currentNetwork.signal : 0)
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: parent.currentNetwork !== null
                        hoverEnabled: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: {
                            root.selectedNetwork = parent.currentNetwork
                            root.page = "details"
                        }
                    }
                }

                Item {
                    width: parent.width
                    height: 29

                    Text {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        text: "Available Networks"
                        color: root.textSecondary
                        font.family: "Inter"
                        font.pixelSize: 12
                        font.weight: Font.Medium
                    }

                    Text {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.wifi.busy ? "Scanning…" : "Refresh"
                        color: root.wifi.wifiEnabled ? root.accent : theme.alpha(root.textSecondary, 0.40)
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
                    height: Math.max(144, mainPage.height - 253)
                    radius: 18
                    color: theme.alpha(root.insetColor, 0.67)
                    border.width: 1
                    border.color: theme.alpha(theme.outline, 0.14)
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
                                chrome: root
                                network: modelData
                                interactionEnabled: !root.wifi.busy
                                onSelected: root.selectNetwork(modelData)
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.leftMargin: 53
                                anchors.right: parent.right
                                anchors.rightMargin: 14
                                anchors.bottom: parent.bottom
                                height: 1
                                color: theme.alpha(theme.outline, 0.10)
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: networksList.count === 0
                            text: !root.wifi.available ? "NetworkManager unavailable"
                                : !root.wifi.wifiEnabled ? "Wi-Fi is turned off"
                                : root.wifi.snapshotReady ? "No networks found" : "Scanning…"
                            color: root.textSecondary
                            font.family: "Inter"
                            font.pixelSize: 12
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: otherRow.top
                        height: 1
                        color: theme.alpha(theme.outline, 0.12)
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
                            color: otherHover.containsMouse ? theme.alpha(root.accent, 0.07) : "transparent"
                        }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 17
                            anchors.verticalCenter: parent.verticalCenter
                            width: 27
                            height: 27
                            radius: 14
                            color: theme.alpha(root.textSecondary, 0.12)
                            Text {
                                anchors.centerIn: parent
                                text: "+"
                                color: root.textSecondary
                                font.family: "Inter"
                                font.pixelSize: 18
                            }
                        }

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 57
                            anchors.verticalCenter: parent.verticalCenter
                            text: "Other Network…"
                            color: root.textPrimary
                            font.family: "Inter"
                            font.pixelSize: 14
                            font.weight: Font.Medium
                        }

                        Text {
                            anchors.right: parent.right
                            anchors.rightMargin: 17
                            anchors.verticalCenter: parent.verticalCenter
                            text: "›"
                            color: root.textSecondary
                            font.family: "Inter"
                            font.pixelSize: 20
                        }

                        MouseArea {
                            id: otherHover
                            anchors.fill: parent
                            enabled: root.wifi.wifiEnabled && !root.wifi.busy
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.page = "manual"
                        }
                    }
                }
            }
        }

        MahoLinkPassword {
            anchors.fill: parent
            visible: root.page === "password"
            chrome: root
            wifi: root.wifi
            network: root.selectedNetwork || ({"ssid": "Wi-Fi"})
            onBackRequested: root.goBack()
        }

        MahoLinkManual {
            anchors.fill: parent
            visible: root.page === "manual"
            chrome: root
            wifi: root.wifi
            onBackRequested: root.goBack()
        }

        MahoLinkDetails {
            anchors.fill: parent
            visible: root.page === "details"
            chrome: root
            wifi: root.wifi
            network: root.selectedNetwork || root.wifi.currentNetwork || ({"ssid": "Wi-Fi"})
            onBackRequested: root.goBack()
        }
    }

    Rectangle {
        z: 5
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 14
        width: Math.min(parent.width - 48, statusText.implicitWidth + 28)
        height: 34
        radius: 17
        visible: statusText.text !== ""
        opacity: visible ? 1 : 0
        color: theme.alpha(root.wifi.errorText !== "" ? theme.error : root.accent, 0.15)
        border.width: 1
        border.color: theme.alpha(root.wifi.errorText !== "" ? theme.error : root.accent, 0.23)

        Text {
            id: statusText
            anchors.centerIn: parent
            width: Math.min(implicitWidth, root.width - 72)
            elide: Text.ElideRight
            text: root.wifi.errorText !== "" ? root.wifi.errorText : root.wifi.actionMessage
            color: root.wifi.errorText !== "" ? theme.error : root.textPrimary
            font.family: "Inter"
            font.pixelSize: 11
        }
    }
}
