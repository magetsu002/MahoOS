import QtQuick

Item {
    id: root

    required property var chrome
    required property var wifi
    required property var network
    signal backRequested()

    property string eapMethod: "peap"
    readonly property bool tlsMode: eapMethod === "tls"
    readonly property bool formReady:
        identityInput.text.trim().length > 0
        && (tlsMode
            ? caCertInput.text.trim().length > 0
                && clientCertInput.text.trim().length > 0
                && privateKeyInput.text.trim().length > 0
                && (domainSuffixInput.text.trim().length > 0
                    || domainMatchInput.text.trim().length > 0)
            : passwordInput.text.length > 0)

    readonly property color glassLow: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.64), 0.42)
    readonly property color glassInteractive: chrome.theme.alpha(
        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56), 0.47)
    readonly property color glassStroke: chrome.theme.alpha(chrome.theme.foreground, 0.055)

    function submit() {
        const identity = identityInput.text.trim()
        if (identity.length === 0) {
            root.wifi.errorText = "Enterprise Wi-Fi identity is required."
            return
        }

        if (root.tlsMode) {
            if (caCertInput.text.trim().length === 0
                    || clientCertInput.text.trim().length === 0
                    || privateKeyInput.text.trim().length === 0) {
                root.wifi.errorText = "EAP-TLS requires CA, client certificate, and private key files."
                return
            }
            if (domainSuffixInput.text.trim().length === 0
                    && domainMatchInput.text.trim().length === 0) {
                root.wifi.errorText = "EAP-TLS requires a server domain or domain suffix."
                return
            }
        } else if (passwordInput.text.length === 0) {
            root.wifi.errorText = "Enterprise Wi-Fi password is required."
            return
        }

        root.wifi.connectEnterprise(String(root.network.ssid || ""), {
            "identity": identity,
            "anonymousIdentity": anonymousInput.text.trim(),
            "password": root.tlsMode ? "" : passwordInput.text,
            "privateKeyPassword": root.tlsMode ? privateKeyPasswordInput.text : "",
            "eap": root.eapMethod,
            "phase2": root.eapMethod === "peap" ? "mschapv2" : "pap",
            "caCert": caCertInput.text.trim(),
            "clientCert": root.tlsMode ? clientCertInput.text.trim() : "",
            "privateKey": root.tlsMode ? privateKeyInput.text.trim() : "",
            "domainSuffix": domainSuffixInput.text.trim(),
            "domainMatch": domainMatchInput.text.trim()
        })
    }

    Flickable {
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: form.implicitHeight
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick

        Column {
            id: form
            width: parent.width
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
                    color: chrome.theme.alpha(
                        chrome.mix(chrome.theme.surfaceHigh, chrome.accent, 0.12), 0.47)
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
                        text: root.tlsMode
                            ? "802.1X · EAP-TLS certificate authentication"
                            : "802.1X enterprise network"
                        color: chrome.theme.alpha(chrome.textSecondary, 0.70)
                        font.family: "Inter"
                        font.pixelSize: 11
                    }
                }
            }

            Text {
                width: parent.width
                wrapMode: Text.WordWrap
                text: root.tlsMode
                    ? "NetworkManager owns the 802.1X profile. Certificate paths are referenced in place; the private-key password stays off process arguments and temporary files."
                    : "NetworkManager owns the 802.1X profile. Passwords stay off process arguments; saved credentials are committed through libnm when available."
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
                    model: ["peap", "ttls", "tls"]

                    Rectangle {
                        required property string modelData
                        width: (parent.width - 16) / 3
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
                            text: modelData === "tls" ? "EAP-TLS" : modelData.toUpperCase()
                            color: root.eapMethod === modelData
                                ? chrome.accent : chrome.textPrimary
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

            MahoLinkEnterpriseField {
                id: identityInput
                width: parent.width
                chrome: root.chrome
                placeholder: "Identity / username"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: anonymousInput
                width: parent.width
                chrome: root.chrome
                placeholder: "Anonymous identity (optional)"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: passwordInput
                width: parent.width
                visible: !root.tlsMode
                chrome: root.chrome
                secret: true
                placeholder: "Password"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: caCertInput
                width: parent.width
                chrome: root.chrome
                placeholder: root.tlsMode
                    ? "CA certificate path (required)"
                    : "CA certificate path (optional)"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: clientCertInput
                width: parent.width
                visible: root.tlsMode
                chrome: root.chrome
                placeholder: "Client certificate path"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: privateKeyInput
                width: parent.width
                visible: root.tlsMode
                chrome: root.chrome
                placeholder: "Private key path"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: privateKeyPasswordInput
                width: parent.width
                visible: root.tlsMode
                chrome: root.chrome
                secret: true
                placeholder: "Private-key password (if encrypted)"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: domainSuffixInput
                width: parent.width
                chrome: root.chrome
                placeholder: root.tlsMode
                    ? "Server domain suffix (required unless exact domain is set)"
                    : "Server domain suffix (optional)"
                onSubmitted: root.submit()
            }

            MahoLinkEnterpriseField {
                id: domainMatchInput
                width: parent.width
                chrome: root.chrome
                placeholder: "Exact server domain / certificate name (optional)"
                onSubmitted: root.submit()
            }

            Text {
                width: parent.width
                visible: root.tlsMode
                wrapMode: Text.WordWrap
                text: "EAP-TLS requires a readable CA certificate, client certificate, private key, and at least one server-name validation field."
                color: chrome.theme.alpha(chrome.textSecondary, 0.62)
                font.family: "Inter"
                font.pixelSize: 9
                lineHeight: 1.25
            }

            Rectangle {
                width: parent.width
                height: 50
                radius: 17
                antialiasing: true
                color: chrome.theme.alpha(chrome.accent,
                    (connectHover.containsMouse || connectHover.activeFocus) ? 0.18 : 0.13)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.22)
                opacity: root.formReady && !root.wifi.busy ? 1 : 0.48

                Text {
                    anchors.centerIn: parent
                    text: root.wifi.activeAction === "connect-enterprise"
                        ? "Connecting…" : "Connect"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }

                MouseArea {
                    id: connectHover
                    anchors.fill: parent
                    enabled: root.formReady && !root.wifi.busy
                    hoverEnabled: true
                    activeFocusOnTab: true
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.submit()
                    Keys.onReturnPressed: root.submit()
                    Keys.onSpacePressed: root.submit()
                }
            }

            Item {
                width: 1
                height: 8
            }
        }
    }

    Component.onCompleted: Qt.callLater(function() { identityInput.focusEditor() })
}
