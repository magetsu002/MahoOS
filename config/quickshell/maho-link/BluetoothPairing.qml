import QtQuick

Item {
    id: root

    required property var chrome
    required property var bluetooth
    required property var device
    property string stage: "Pairing…"

    signal cancelRequested()

    readonly property string promptKind: String(bluetooth.pairingPromptKind || "")
    readonly property string promptValue: String(bluetooth.pairingPromptValue || "")
    readonly property bool needsInput:
        promptKind === "pin" || promptKind === "passkey"
    readonly property bool needsDecision:
        promptKind === "confirm"
        || promptKind === "authorize"
        || promptKind === "authorize-service"
    readonly property bool displayOnly:
        promptKind === "display-pin" || promptKind === "display-passkey"
    readonly property bool promptVisible:
        needsInput || needsDecision || displayOnly

    function promptTitle() {
        switch (root.promptKind) {
        case "pin": return "Enter PIN"
        case "passkey": return "Enter Passkey"
        case "confirm": return "Confirm This Code"
        case "authorize": return "Allow Pairing?"
        case "authorize-service": return "Authorize Bluetooth Service?"
        case "display-pin":
        case "display-passkey":
            return "Enter This Code on the Device"
        default:
            return root.stage
        }
    }

    function promptDescription() {
        switch (root.promptKind) {
        case "pin":
            return "BlueZ is requesting the device PIN."
        case "passkey":
            return "BlueZ is requesting a six-digit passkey."
        case "confirm":
            return "Confirm that this number matches the one shown on the other device."
        case "authorize":
            return "BlueZ is asking whether this device may pair with MahoOS."
        case "authorize-service":
            return root.bluetooth.pairingServiceUuid
                ? "BlueZ is asking to authorize service " + root.bluetooth.pairingServiceUuid + "."
                : "BlueZ is asking to authorize a Bluetooth service."
        case "display-pin":
        case "display-passkey":
            return "Type this code on the other device when it asks."
        default:
            return "Make sure your device is in pairing mode and nearby."
        }
    }

    function submitPrompt() {
        if (!root.needsInput && !root.needsDecision)
            return
        const value = root.needsInput ? pairingInput.text.trim() : ""
        if (root.needsInput && value.length === 0) {
            root.bluetooth.pairingInputError = root.promptKind === "passkey"
                ? "Enter the passkey first."
                : "Enter the PIN first."
            return
        }
        if (root.bluetooth.respondPairing(true, value))
            pairingInput.text = ""
    }

    function rejectPrompt() {
        root.bluetooth.respondPairing(false, "")
    }

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 54, 360)
        spacing: 13

        Item {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 116
            height: 116

            Item {
                id: orbit
                anchors.fill: parent

                Repeater {
                    model: 18
                    delegate: Rectangle {
                        required property int index
                        width: 5
                        height: 5
                        radius: 3
                        x: orbit.width / 2 + Math.cos((index / 18) * Math.PI * 2) * 49 - width / 2
                        y: orbit.height / 2 + Math.sin((index / 18) * Math.PI * 2) * 49 - height / 2
                        color: chrome.accent
                        opacity: 0.15 + (index / 18) * 0.72
                    }
                }

                RotationAnimation on rotation {
                    running: root.visible && root.bluetooth.pairingActive
                    from: 0
                    to: 360
                    duration: 2500
                    loops: Animation.Infinite
                    easing.type: Easing.Linear
                }
            }

            Rectangle {
                anchors.centerIn: parent
                width: 68
                height: 68
                radius: 34
                color: chrome.theme.alpha(chrome.accent, 0.075)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.outline, 0.09)

                Text {
                    anchors.centerIn: parent
                    text: "󰂯"
                    color: chrome.textPrimary
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 30
                }
            }
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: root.promptVisible ? root.promptTitle() : root.stage
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 19
            font.weight: Font.DemiBold
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.promptDescription()
            color: chrome.theme.alpha(chrome.textSecondary, 0.78)
            font.family: "Inter"
            font.pixelSize: 10
            lineHeight: 1.25
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: String(root.device && root.device.name
                ? root.device.name : "Bluetooth Device")
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 13
            font.weight: Font.Medium
        }

        Rectangle {
            width: parent.width
            height: root.promptVisible ? 76 : 3
            radius: root.promptVisible ? 18 : 2
            color: root.promptVisible
                ? chrome.theme.alpha(
                    chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56), 0.47)
                : chrome.theme.alpha(chrome.textSecondary, 0.12)
            border.width: root.promptVisible ? 1 : 0
            border.color: chrome.theme.alpha(chrome.theme.foreground, 0.055)
            clip: true

            Rectangle {
                visible: !root.promptVisible
                width: parent.width * 0.58
                height: parent.height
                radius: parent.radius
                color: chrome.accent

                SequentialAnimation on x {
                    running: root.visible && !root.promptVisible
                    loops: Animation.Infinite
                    NumberAnimation {
                        from: -116
                        to: 360
                        duration: 1350
                        easing.type: Easing.InOutCubic
                    }
                }
            }

            Text {
                anchors.centerIn: parent
                visible: (root.needsDecision || root.displayOnly)
                    && root.promptValue.length > 0
                text: root.promptValue
                color: chrome.textPrimary
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 27
                font.weight: Font.DemiBold
                font.letterSpacing: 2
            }

            TextInput {
                id: pairingInput
                anchors.fill: parent
                anchors.leftMargin: 18
                anchors.rightMargin: 18
                visible: root.needsInput
                enabled: visible && root.bluetooth.pairingActive
                verticalAlignment: TextInput.AlignVCenter
                horizontalAlignment: TextInput.AlignHCenter
                activeFocusOnTab: true
                maximumLength: root.promptKind === "passkey" ? 6 : 16
                inputMethodHints: root.promptKind === "passkey"
                    ? Qt.ImhDigitsOnly : Qt.ImhNone
                color: chrome.textPrimary
                selectionColor: chrome.theme.alpha(chrome.accent, 0.30)
                selectedTextColor: chrome.textPrimary
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 20
                font.letterSpacing: 1
                clip: true
                Keys.onReturnPressed: root.submitPrompt()
            }

            Text {
                anchors.centerIn: parent
                visible: root.needsInput
                    && pairingInput.text.length === 0
                    && !pairingInput.activeFocus
                text: root.promptKind === "passkey"
                    ? "000000" : "Enter PIN"
                color: chrome.theme.alpha(chrome.textSecondary, 0.48)
                font.family: "Inter"
                font.pixelSize: 12
            }
        }

        Text {
            width: parent.width
            visible: String(root.bluetooth.pairingInputError || "") !== ""
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: String(root.bluetooth.pairingInputError || "")
            color: chrome.theme.error
            font.family: "Inter"
            font.pixelSize: 9
        }

        Row {
            width: parent.width
            height: (root.needsInput || root.needsDecision) ? 43 : 0
            visible: height > 0
            spacing: 10

            Rectangle {
                width: (parent.width - 10) / 2
                height: parent.height
                radius: 14
                color: rejectHover.containsMouse || rejectHover.activeFocus
                    ? chrome.theme.alpha(chrome.theme.error, 0.13)
                    : chrome.theme.alpha(chrome.theme.error, 0.075)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.error, 0.10)

                Text {
                    anchors.centerIn: parent
                    text: "Reject"
                    color: chrome.theme.error
                    font.family: "Inter"
                    font.pixelSize: 11
                    font.weight: Font.Medium
                }

                MouseArea {
                    id: rejectHover
                    anchors.fill: parent
                    enabled: root.bluetooth.pairingActive
                    hoverEnabled: true
                    activeFocusOnTab: true
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.rejectPrompt()
                    Keys.onReturnPressed: root.rejectPrompt()
                    Keys.onSpacePressed: root.rejectPrompt()
                }
            }

            Rectangle {
                width: (parent.width - 10) / 2
                height: parent.height
                radius: 14
                color: acceptHover.containsMouse || acceptHover.activeFocus
                    ? chrome.theme.alpha(chrome.accent, 0.20)
                    : chrome.theme.alpha(chrome.accent, 0.13)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.accent, 0.19)

                Text {
                    anchors.centerIn: parent
                    text: root.needsDecision ? "Confirm" : "Continue"
                    color: chrome.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                }

                MouseArea {
                    id: acceptHover
                    anchors.fill: parent
                    enabled: root.bluetooth.pairingActive
                    hoverEnabled: true
                    activeFocusOnTab: true
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.submitPrompt()
                    Keys.onReturnPressed: root.submitPrompt()
                    Keys.onSpacePressed: root.submitPrompt()
                }
            }
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: root.bluetooth.activeAction === "connect" ? "Connecting…"
                : root.bluetooth.pairingActive ? "BlueZ pairing session active"
                : root.stage
            color: chrome.theme.alpha(chrome.textSecondary, 0.68)
            font.family: "Inter"
            font.pixelSize: 9
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 150
            height: 43
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

                function activate() {
                    root.bluetooth.cancelPairing(root.device)
                    root.cancelRequested()
                }

                onClicked: activate()
                Keys.onReturnPressed: activate()
                Keys.onSpacePressed: activate()
            }
        }
    }

    Connections {
        target: root.bluetooth
        function onPairingPromptRequestIdChanged() {
            pairingInput.text = ""
            if (root.bluetooth.pairingPromptRequestId > 0 && root.needsInput)
                Qt.callLater(function() { pairingInput.forceActiveFocus() })
        }
    }
}
