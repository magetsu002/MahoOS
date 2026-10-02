import QtQuick

Item {
    id: root

    required property var chrome
    required property var wifi
    required property var network
    signal backRequested()

    property string eapMethod: "peap"
    readonly property color glassLow: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.64), 0.42)
    readonly property color glassInteractive: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56), 0.47)
    readonly property color glassStroke: chrome.theme.alpha(chrome.theme.foreground, 0.055)
    readonly property color glassHighlight: chrome.theme.alpha(chrome.theme.foreground, 0.050)

    function submit() {
        const identity = identityInput.text.trim()
        const password = passwordInput.text
        if (identity.length === 0 || password.length === 0) {
            root.wifi.errorText = "Identity and password are required."
            return
        }
        root.wifi.connectEnterprise(String(root.network.ssid || ""), {
            "identity": identity,
            "password": password,
            "eap": root.eapMethod,
            "phase2": root.eapMethod === "peap" ? "mschapv2" : "pap",
            "domainSuffix": domainInput.text.trim()
        })
    }

    Column {
        anchors.fill: parent
        spacing: 13

        Rectangle {
            width: parent.width
            height: 112
            radius: 20
            antialiasing: true
            color: root.glassLow
            border.width: 1
            border.color: root.glassStroke

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                width: 58
                height: 58
                radius: 19
                antialiasing: true
                color: chrome.theme.alpha(chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.12), 0.47)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.09)

                MahoWifiGlyph {
                    anchors.centerIn: parent
                    width: 30
                    height: 30
                    glyphColor: chrome.theme.alpha(chrome.accent, 0.92)
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 92
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5

                Text {
                    width: parent.width
                    text: String(root.network.ssid || "Enterprise Wi-Fi")
                    color: chrome.textPrimary
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: 17
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: "802.1X enterprise network"
                    color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                    font.family: "Inter"
                    font.pixelSize: 11
                }
            }
        }

        Text {
            width: parent.width
            wrapMode: Text.WordWrap
            text: "Maho Link creates a NetworkManager 802.1X profile. Passwords stay off process arguments; saved credentials are committed through libnm when available."
            color: chrome.theme.alpha(chrome.textSecondary, 0.70)
            font.family: "Inter"
            font.pixelSize: 10
            lineHeight: 1.25
        }

        Row {
            width: parent.width
            height: 40
            spacing: 8

            Repeater {
                model: ["peap", "ttls"]

                Rectangle {
                    required property string modelData
                    width: (parent.width - 8) / 2
                    height: 40
                    radius: 14
                    antialiasing: true
                    color: root.eapMethod === modelData
                        ? chrome.theme.alpha(chrome.accent, 0.14)
                        : root.glassInteractive
                    border.width: 1
                    border.color: root.eapMethod === modelData
                        ? chrome.theme.alpha(chrome.accent, 0.24)
                        : root.glassStroke

                    Text {
                        anchors.centerIn: parent
                        text: modelData.toUpperCase()
                        color: root.eapMethod === modelData ? chrome.accent : chrome.textPrimary
                        font.family: "Inter"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                    }

                    MouseArea {
                        anchors.fill: parent
                        enabled: !root.wifi.busy
                        hoverEnabled: true
                        activeFocusOnTab: true
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.eapMethod = modelData
                        Keys.onReturnPressed: root.eapMethod = modelData
                        Keys.onSpacePressed: root.eapMethod = modelData
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 56
            radius: 16
            antialiasing: true
            color: root.glassInteractive
            border.width: 1
            border.color: identityInput.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.26) : root.glassStroke

            TextInput {
                id: identityInput
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                verticalAlignment: TextInput.AlignVCenter
                activeFocusOnTab: true
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.30)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 12
                clip: true
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                visible: identityInput.text.length === 0 && !identityInput.activeFocus
                text: "Identity / username"
                color: chrome.theme.alpha(chrome.textSecondary, 0.58)
                font.family: "Inter"
                font.pixelSize: 11
            }
        }

        Rectangle {
            width: parent.width
            height: 56
            radius: 16
            antialiasing: true
            color: root.glassInteractive
            border.width: 1
            border.color: passwordInput.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.26) : root.glassStroke

            TextInput {
                id: passwordInput
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                verticalAlignment: TextInput.AlignVCenter
                activeFocusOnTab: true
                echoMode: TextInput.Password
                passwordCharacter: "•"
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.30)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 12
                clip: true
                Keys.onReturnPressed: root.submit()
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                visible: passwordInput.text.length === 0 && !passwordInput.activeFocus
                text: "Password"
                color: chrome.theme.alpha(chrome.textSecondary, 0.58)
                font.family: "Inter"
                font.pixelSize: 11
            }
        }

        Rectangle {
            width: parent.width
            height: 52
            radius: 16
            antialiasing: true
            color: root.glassInteractive
            border.width: 1
            border.color: domainInput.activeFocus
                ? chrome.theme.alpha(chrome.accent, 0.26) : root.glassStroke

            TextInput {
                id: domainInput
                anchors.fill: parent
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                verticalAlignment: TextInput.AlignVCenter
                activeFocusOnTab: true
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.30)
                selectedTextColor: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 12
                clip: true
                Keys.onReturnPressed: root.submit()
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 16
                anchors.verticalCenter: parent.verticalCenter
                visible: domainInput.text.length === 0 && !domainInput.activeFocus
                text: "Server domain suffix (optional)"
                color: chrome.theme.alpha(chrome.textSecondary, 0.58)
                font.family: "Inter"
                font.pixelSize: 11
            }
        }

        Item { width: 1; height: 2 }

        Rectangle {
            width: parent.width
            height: 50
            radius: 17
            antialiasing: true
            color: chrome.theme.alpha(chrome.accent,
                (connectHover.containsMouse || connectHover.activeFocus) ? 0.18 : 0.13)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.accent, 0.22)
            opacity: identityInput.text.trim().length > 0
                && passwordInput.text.length > 0 && !root.wifi.busy ? 1 : 0.48

            Text {
                anchors.centerIn: parent
                text: root.wifi.activeAction === "connect-enterprise" ? "Connecting…" : "Connect"
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }

            MouseArea {
                id: connectHover
                anchors.fill: parent
                enabled: identityInput.text.trim().length > 0
                    && passwordInput.text.length > 0 && !root.wifi.busy
                hoverEnabled: true
                activeFocusOnTab: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: root.submit()
                Keys.onReturnPressed: root.submit()
                Keys.onSpacePressed: root.submit()
            }
        }
    }

    Component.onCompleted: Qt.callLater(function() { identityInput.forceActiveFocus() })
}
