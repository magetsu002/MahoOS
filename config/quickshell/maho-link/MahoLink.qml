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

    readonly property bool compactMain:
        page === "main"
        && wifi.snapshotReady
        && wifi.wifiEnabled
        && wifi.networks
        && wifi.networks.length === 0

    width: 486
    height: compactMain
        ? Math.min(470, Math.max(430, availableHeight - 40))
        : Math.min(652, Math.max(500, availableHeight - 40))
    focus: shown
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.988
    transform: Translate {
        y: root.shown ? 0 : -10
        Behavior on y { NumberAnimation { duration: root.shown ? 210 : 150; easing.type: Easing.OutCubic } }
    }

    Behavior on height { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
    Behavior on opacity { NumberAnimation { duration: shown ? 210 : 150; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: shown ? 210 : 150; easing.type: Easing.OutCubic } }

    readonly property color textPrimary: theme.foreground
    readonly property color textSecondary: theme.alpha(theme.muted, 0.78)
    readonly property color insetColor: mix(theme.surfaceHigh, theme.background, 0.36)
    readonly property color accent: stableAccent(theme.primary)
    readonly property color shellFill: theme.alpha(mix(theme.surfaceHigh, theme.background, 0.28), 0.985)

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
            if (root.wifi.actionMessage !== "" && root.page !== "main") {
                root.page = "main"
                root.selectedNetwork = null
            }
        }
        function onWifiEnabledChanged() {
            if (!root.wifi.wifiEnabled && root.page !== "main") {
                root.page = "main"
                root.selectedNetwork = null
            }
        }
    }

    // A very soft accent halo separates the surface without drawing a visible
    // second outline around it.
    Rectangle {
        anchors.fill: parent
        anchors.margins: -4
        radius: 27
        color: theme.alpha(root.accent, 0.025)
        opacity: 0.64
    }

    Rectangle {
        anchors.fill: parent
        radius: 24
        color: root.shellFill
        border.width: 1
        border.color: theme.alpha(theme.outline, 0.11)
        clip: true

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 150
            gradient: Gradient {
                GradientStop { position: 0; color: theme.alpha(root.accent, 0.045) }
                GradientStop { position: 1; color: "transparent" }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 24
            anchors.rightMargin: 24
            anchors.top: parent.top
            height: 1
            color: theme.alpha(theme.foreground, 0.035)
        }
    }

    // Prevent the full-screen outside-click catcher from receiving blank panel clicks.
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
        anchors.topMargin: 19
        height: 40

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            height: 34
            radius: 11
            color: backHover.containsMouse ? theme.alpha(root.accent, 0.075) : "transparent"

            Text {
                anchors.centerIn: parent
                text: "‹"
                color: root.textPrimary
                font.family: "Inter"
                font.pixelSize: 29
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
                width: 44
                height: 26
                radius: 13
                color: root.wifi.wifiEnabled
                    ? theme.alpha(root.accent, toggleHover.containsMouse ? 0.84 : 0.74)
                    : theme.alpha(root.textSecondary, 0.15)
                border.width: 1
                border.color: root.wifi.wifiEnabled
                    ? theme.alpha(root.accent, 0.24)
                    : theme.alpha(theme.outline, 0.12)
                opacity: root.wifi.available && !root.wifi.busy ? 1 : 0.48

                Rectangle {
                    width: 20
                    height: 20
                    radius: 10
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
                width: 30
                height: 30
                radius: 10
                color: closeHover.containsMouse ? theme.alpha(root.textSecondary, 0.075) : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: theme.alpha(root.textSecondary, 0.88)
                    font.family: "Inter"
                    font.pixelSize: 20
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
        anchors.topMargin: 13
        anchors.bottomMargin: 18

        MahoLinkMain {
            anchors.fill: parent
            visible: root.page === "main"
            chrome: root
            wifi: root.wifi
            onNetworkSelected: function(network) { root.selectNetwork(network) }
            onDetailsRequested: function(network) {
                root.selectedNetwork = network
                root.page = "details"
            }
            onManualRequested: root.page = "manual"
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
        color: theme.alpha(root.wifi.errorText !== "" ? theme.error : root.accent, 0.15)
        border.width: 1
        border.color: theme.alpha(root.wifi.errorText !== "" ? theme.error : root.accent, 0.18)

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
