import QtQuick

Item {
    id: root

    required property var chrome
    required property var bluetooth
    required property var device
    property string stage: "Pairing…"

    signal cancelRequested()

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 54, 350)
        spacing: 16

        Item {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 150
            height: 150

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
                        x: orbit.width / 2 + Math.cos((index / 18) * Math.PI * 2) * 66 - width / 2
                        y: orbit.height / 2 + Math.sin((index / 18) * Math.PI * 2) * 66 - height / 2
                        color: chrome.accent
                        opacity: 0.15 + (index / 18) * 0.72
                    }
                }

                RotationAnimation on rotation {
                    running: root.visible
                    from: 0
                    to: 360
                    duration: 2500
                    loops: Animation.Infinite
                    easing.type: Easing.Linear
                }
            }

            Rectangle {
                anchors.centerIn: parent
                width: 80
                height: 80
                radius: 40
                color: chrome.theme.alpha(chrome.accent, 0.075)
                border.width: 1
                border.color: chrome.theme.alpha(chrome.theme.outline, 0.09)

                Text {
                    anchors.centerIn: parent
                    text: "󰂯"
                    color: chrome.textPrimary
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 34
                }
            }
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: root.stage
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 20
            font.weight: Font.DemiBold
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Make sure your device is in pairing mode and nearby."
            color: chrome.theme.alpha(chrome.textSecondary, 0.78)
            font.family: "Inter"
            font.pixelSize: 11
            lineHeight: 1.28
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: String(root.device && root.device.name ? root.device.name : "Bluetooth Device")
            color: chrome.textPrimary
            font.family: "Inter"
            font.pixelSize: 13
            font.weight: Font.Medium
        }

        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter
            width: 170
            height: 3
            radius: 2
            color: chrome.theme.alpha(chrome.textSecondary, 0.12)
            clip: true

            Rectangle {
                width: parent.width * 0.58
                height: parent.height
                radius: parent.radius
                color: chrome.accent

                SequentialAnimation on x {
                    running: root.visible
                    loops: Animation.Infinite
                    NumberAnimation { from: -116; to: 170; duration: 1350; easing.type: Easing.InOutCubic }
                }
            }
        }

        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: root.bluetooth.activeAction === "connect" ? "Connecting…"
                : root.bluetooth.activeAction === "pair" ? "Waiting for pairing…"
                : root.stage
            color: chrome.theme.alpha(chrome.textSecondary, 0.78)
            font.family: "Inter"
            font.pixelSize: 10
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
}
