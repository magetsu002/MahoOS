import QtQuick

Item {
    id: root

    required property var theme
    required property var wifi
    required property var bluetooth
    required property real availableHeight
    property bool shown: false
    property string section: "wifi"
    property string page: "main"
    property var selectedNetwork: null
    property var selectedBluetoothDevice: null
    property string pairingStage: "Pairing…"

    signal closeRequested()

    readonly property bool compactMain:
        section === "wifi"
        && page === "main"
        && wifi.snapshotReady
        && wifi.wifiEnabled
        && wifi.networks
        && wifi.networks.length === 0

    readonly property var activeState: section === "bluetooth" ? bluetooth : wifi
    readonly property string statusError: section === "bluetooth" ? bluetooth.errorText : wifi.errorText
    readonly property string statusMessage: section === "bluetooth" ? bluetooth.actionMessage : wifi.actionMessage

    width: 486
    height: section === "bluetooth"
        ? Math.min(652, Math.max(560, availableHeight - 40))
        : compactMain
            ? Math.min(470, Math.max(430, availableHeight - 40))
            : Math.min(652, Math.max(500, availableHeight - 40))
    focus: shown
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.985
    transform: Translate {
        y: root.shown ? 0 : -7

        Behavior on y {
            NumberAnimation { duration: root.shown ? 235 : 105; easing.type: Easing.OutCubic }
        }
    }
    Behavior on height {
        enabled: root.shown
        NumberAnimation { duration: 86; easing.type: Easing.OutCubic }
    }
    Behavior on opacity {
        NumberAnimation { duration: root.shown ? 205 : 110; easing.type: Easing.OutCubic }
    }
    Behavior on scale {
        NumberAnimation { duration: root.shown ? 220 : 105; easing.type: Easing.OutCubic }
    }

    readonly property color textPrimary: theme.foreground
    readonly property color textSecondary: theme.alpha(theme.muted, 0.78)
    readonly property color insetColor: mix(theme.surfaceHigh, theme.background, 0.36)
    readonly property color accent: stableAccent(theme.primary)

    // Hyprland supplies diffusion behind this material; QML supplies tint,
    // depth and contrast. Keep one quiet translucent wash so blurred content
    // becomes color/liquidity instead of readable background detail.
    readonly property color neutralGlass: mix(theme.surfaceHigh, theme.background, 0.54)
    readonly property color shellFill: theme.alpha(neutralGlass, 0.72)
    readonly property color shellStroke: theme.alpha(theme.foreground, 0.105)

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
        if (section === "bluetooth" && page === "forget") {
            page = "details"
            return
        }
        page = "main"
        selectedNetwork = null
        selectedBluetoothDevice = null
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

    function selectBluetoothDevice(device) {
        if (!device)
            return
        selectedBluetoothDevice = device
        page = "details"
    }

    function pairBluetoothDevice(device) {
        if (!device || bluetooth.busy)
            return
        selectedBluetoothDevice = device
        pairingStage = "Pairing…"
        page = "pairing"
        if (!bluetooth.pairDevice(device)) {
            page = "main"
            selectedBluetoothDevice = null
        }
    }

    function syncSelectedBluetoothDevice() {
        if (!selectedBluetoothDevice || !selectedBluetoothDevice.path)
            return
        const path = String(selectedBluetoothDevice.path)
        const sources = [bluetooth.pairedDevices || [], bluetooth.availableDevices || [], bluetooth.connectedDevices || []]
        for (let s = 0; s < sources.length; ++s) {
            for (let i = 0; i < sources[s].length; ++i) {
                if (String(sources[s][i].path || "") === path) {
                    selectedBluetoothDevice = sources[s][i]
                    return
                }
            }
        }
    }

    Keys.onEscapePressed: root.closeRequested()

    Connections {
        target: root.wifi
        function onActionMessageChanged() {
            if (root.section === "wifi" && root.wifi.actionMessage !== "" && root.page !== "main") {
                root.page = "main"
                root.selectedNetwork = null
            }
        }
        function onWifiEnabledChanged() {
            if (root.section === "wifi" && !root.wifi.wifiEnabled && root.page !== "main") {
                root.page = "main"
                root.selectedNetwork = null
            }
        }
    }

    Connections {
        target: root.bluetooth

        function onBluetoothEnabledChanged() {
            if (root.section === "bluetooth" && !root.bluetooth.bluetoothEnabled && root.page !== "main") {
                root.page = "main"
                root.selectedBluetoothDevice = null
            }
        }
        function onPairedDevicesChanged() { root.syncSelectedBluetoothDevice() }
        function onAvailableDevicesChanged() { root.syncSelectedBluetoothDevice() }
        function onConnectedDevicesChanged() { root.syncSelectedBluetoothDevice() }

        function onActionSucceeded(action, devicePath) {
            if (root.section !== "bluetooth")
                return
            if (action === "pair" && root.page === "pairing" && root.selectedBluetoothDevice) {
                root.pairingStage = "Connecting…"
                if (!root.bluetooth.connectDevice(root.selectedBluetoothDevice))
                    root.page = "main"
                return
            }
            if (action === "connect") {
                if (root.page === "pairing")
                    root.page = "details"
                return
            }
            if (action === "disconnect")
                return
            if (action === "forget") {
                root.page = "main"
                root.selectedBluetoothDevice = null
            }
        }

        function onActionFailed(action, devicePath) {
            if (root.section === "bluetooth" && root.page === "pairing" && (action === "pair" || action === "connect")) {
                root.page = "main"
                root.selectedBluetoothDevice = null
            }
        }
    }

    Rectangle {
        id: shellMaterial
        anchors.fill: parent
        radius: 24
        antialiasing: true
        color: root.shellFill
        border.width: 1
        border.color: root.shellStroke

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
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.topMargin: 18
        height: 40

        Rectangle {
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 32
            height: 32
            radius: 10
            antialiasing: true
            color: backHover.containsMouse
                ? theme.alpha(theme.foreground, 0.045)
                : "transparent"

            Text {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: -1
                text: "‹"
                color: root.textPrimary
                font.family: "Inter"
                font.pixelSize: 28
                font.weight: Font.Light
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
            width: parent.width - 150
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: root.section === "bluetooth"
                ? (root.page === "details" && root.selectedBluetoothDevice
                    ? String(root.selectedBluetoothDevice.name || "Bluetooth Device")
                    : root.page === "forget" ? "Forget Device" : "Bluetooth")
                : root.page === "main" ? "Wi-Fi"
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
                id: wifiToggleTrack
                visible: root.section === "wifi" && root.page === "main"
                width: visible ? 46 : 0
                height: 27
                radius: 14
                antialiasing: true
                opacity: root.wifi.available && !root.wifi.busy ? 1 : 0.48
                color: root.wifi.wifiEnabled
                    ? theme.alpha(root.accent, toggleHover.containsMouse ? 0.77 : 0.67)
                    : theme.alpha(theme.surfaceHigh, 0.42)
                border.width: 1
                border.color: root.wifi.wifiEnabled
                    ? theme.alpha(root.accent, 0.22)
                    : theme.alpha(theme.foreground, 0.075)

                Behavior on color { ColorAnimation { duration: 150 } }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 8
                    anchors.rightMargin: 8
                    anchors.top: parent.top
                    height: 1
                    radius: 1
                    antialiasing: true
                    color: theme.alpha(theme.foreground, 0.13)
                }

                Rectangle {
                    width: 22
                    height: 22
                    radius: 11
                    antialiasing: true
                    y: 4
                    x: root.wifi.wifiEnabled ? parent.width - width - 2 : 2
                    color: Qt.rgba(0, 0, 0, 0.20)
                    opacity: 0.68
                    Behavior on x { NumberAnimation { duration: 175; easing.type: Easing.OutCubic } }
                }

                Rectangle {
                    width: 21
                    height: 21
                    radius: 11
                    antialiasing: true
                    y: 3
                    x: root.wifi.wifiEnabled ? parent.width - width - 3 : 3
                    color: Qt.rgba(0.99, 0.99, 0.99, 0.985)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.46)
                    Behavior on x { NumberAnimation { duration: 175; easing.type: Easing.OutCubic } }
                }

                MouseArea {
                    id: toggleHover
                    anchors.fill: parent
                    enabled: root.wifi.available && !root.wifi.busy
                    hoverEnabled: true
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.wifi.setWifiEnabled(!root.wifi.wifiEnabled)
                }
            }

            Rectangle {
                width: 32
                height: 32
                radius: 10
                antialiasing: true
                color: closeHover.containsMouse
                    ? theme.alpha(theme.foreground, 0.045)
                    : "transparent"

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
        anchors.leftMargin: 20
        anchors.rightMargin: 20
        anchors.topMargin: 12
        anchors.bottomMargin: 18

        MahoLinkMain {
            anchors.fill: parent
            visible: root.section === "wifi" && root.page === "main"
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
            visible: root.section === "wifi" && root.page === "password"
            chrome: root
            wifi: root.wifi
            network: root.selectedNetwork || ({"ssid": "Wi-Fi"})
            onBackRequested: root.goBack()
        }

        MahoLinkManual {
            anchors.fill: parent
            visible: root.section === "wifi" && root.page === "manual"
            chrome: root
            wifi: root.wifi
            onBackRequested: root.goBack()
        }

        MahoLinkDetails {
            anchors.fill: parent
            visible: root.section === "wifi" && root.page === "details"
            chrome: root
            wifi: root.wifi
            network: root.selectedNetwork || root.wifi.currentNetwork || ({"ssid": "Wi-Fi"})
            onBackRequested: root.goBack()
        }

        BluetoothMain {
            anchors.fill: parent
            visible: root.section === "bluetooth" && root.page === "main"
            chrome: root
            bluetooth: root.bluetooth
            onDetailsRequested: function(device) { root.selectBluetoothDevice(device) }
            onPairRequested: function(device) { root.pairBluetoothDevice(device) }
        }

        BluetoothPairing {
            anchors.fill: parent
            visible: root.section === "bluetooth" && root.page === "pairing"
            chrome: root
            bluetooth: root.bluetooth
            device: root.selectedBluetoothDevice || ({"name": "Bluetooth Device"})
            stage: root.pairingStage
            onCancelRequested: {
                root.page = "main"
                root.selectedBluetoothDevice = null
            }
        }

        BluetoothDetails {
            anchors.fill: parent
            visible: root.section === "bluetooth" && root.page === "details"
            chrome: root
            bluetooth: root.bluetooth
            device: root.selectedBluetoothDevice || ({"name": "Bluetooth Device", "type": "Bluetooth Device"})
            onForgetRequested: root.page = "forget"
        }

        BluetoothForgetConfirmation {
            anchors.fill: parent
            visible: root.section === "bluetooth" && root.page === "forget"
            chrome: root
            bluetooth: root.bluetooth
            device: root.selectedBluetoothDevice || ({"name": "Bluetooth Device"})
            onCancelRequested: root.page = "details"
            onConfirmed: root.bluetooth.forgetDevice(root.selectedBluetoothDevice)
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
        antialiasing: true
        visible: statusText.text !== ""
        color: theme.alpha(root.statusError !== "" ? theme.error : root.accent, 0.15)
        border.width: 1
        border.color: theme.alpha(root.statusError !== "" ? theme.error : root.accent, 0.18)

        Text {
            id: statusText
            anchors.centerIn: parent
            width: Math.min(implicitWidth, root.width - 72)
            elide: Text.ElideRight
            text: root.statusError !== "" ? root.statusError : root.statusMessage
            color: root.statusError !== "" ? theme.error : root.textPrimary
            font.family: "Inter"
            font.pixelSize: 11
        }
    }
}
