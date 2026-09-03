import QtQuick

Item {
    id: root

    required property var chrome
    required property var device
    property string actionLabel: ""
    property bool interactionEnabled: true

    signal selected()
    signal actionRequested()

    function glyph(kind) {
        switch (String(kind || "generic")) {
        case "headphones": return "󰋋"
        case "speaker": return "󰓃"
        case "keyboard": return "󰌌"
        case "mouse": return "󰍽"
        case "controller": return "󰊴"
        case "phone": return "󰏲"
        case "computer": return "󰍹"
        default: return "󰂯"
        }
    }

    Rectangle {
        id: rowHoverPlane
        anchors.fill: parent
        anchors.margins: 3
        radius: 14
        antialiasing: true
        color: chrome.theme.alpha(chrome.theme.foreground, 0.028)
        opacity: rowHover.containsMouse ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        id: deviceIcon
        anchors.left: parent.left
        anchors.leftMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        width: 34
        height: 34
        radius: 13
        antialiasing: true
        color: chrome.theme.alpha(
            chrome.mix(
                chrome.theme.surfaceHigh,
                device.connected ? chrome.accent : chrome.theme.background,
                device.connected ? 0.10 : 0.22
            ),
            0.48
        )
        border.width: 1
        border.color: chrome.theme.alpha(
            device.connected ? chrome.accent : chrome.theme.foreground,
            device.connected ? 0.095 : 0.055
        )

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            height: 1
            radius: 1
            antialiasing: true
            color: chrome.theme.alpha(chrome.theme.foreground, 0.060)
        }

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            antialiasing: true
            gradient: Gradient {
                GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.018) }
                GradientStop { position: 0.55; color: "transparent" }
                GradientStop { position: 1; color: chrome.theme.alpha(device.connected ? chrome.accent : chrome.theme.background, 0.018) }
            }
        }

        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -1
            text: root.glyph(device.kind)
            color: device.connected ? chrome.accent : chrome.theme.alpha(chrome.textSecondary, 0.88)
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 18
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            renderType: Text.NativeRendering
        }
    }

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 58
        anchors.right: actionArea.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3

        Text {
            width: parent.width
            text: String(device.name || "Bluetooth Device")
            color: chrome.textPrimary
            elide: Text.ElideRight
            font.family: "Inter"
            font.pixelSize: 13
            font.weight: Font.Medium
        }

        Text {
            width: parent.width
            text: device.connected
                ? (device.battery !== null && device.battery !== undefined
                    ? "Connected · " + String(device.battery) + "% battery"
                    : "Connected")
                : String(device.type || "Bluetooth Device")
            color: device.connected
                ? chrome.theme.alpha(chrome.accent, 0.84)
                : chrome.theme.alpha(chrome.textSecondary, 0.66)
            elide: Text.ElideRight
            font.family: "Inter"
            font.pixelSize: 10
        }
    }

    Item {
        id: actionArea
        anchors.right: parent.right
        anchors.rightMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        width: root.actionLabel !== "" ? 68 : 28
        height: 34

        Rectangle {
            anchors.centerIn: parent
            width: parent.width
            height: 30
            visible: root.actionLabel !== ""
            radius: 12
            antialiasing: true
            scale: actionHover.pressed ? 0.985 : 1
            color: chrome.theme.alpha(chrome.theme.surfaceHigh, 0.27)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.foreground, 0.050)

            Behavior on scale {
                NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
            }

            Rectangle {
                id: actionHoverPlane
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                color: chrome.theme.alpha(chrome.accent, 0.10)
                opacity: actionHover.containsMouse ? 1 : 0

                Behavior on opacity {
                    NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 9
                anchors.rightMargin: 9
                height: 1
                radius: 1
                antialiasing: true
                color: chrome.theme.alpha(chrome.theme.foreground, 0.050)
            }

            Text {
                anchors.centerIn: parent
                text: root.actionLabel
                color: chrome.accent
                font.family: "Inter"
                font.pixelSize: 10
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                renderType: Text.NativeRendering
            }
        }

        Text {
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -1
            visible: root.actionLabel === ""
            text: "›"
            color: chrome.theme.alpha(chrome.textSecondary, 0.64)
            font.family: "Inter"
            font.pixelSize: 22
            font.weight: Font.Light
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            renderType: Text.NativeRendering
        }

        MouseArea {
            id: actionHover
            anchors.fill: parent
            enabled: root.interactionEnabled
            hoverEnabled: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: {
                if (root.actionLabel !== "")
                    root.actionRequested()
                else
                    root.selected()
            }
        }
    }

    MouseArea {
        id: rowHover
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: actionArea.left
        hoverEnabled: true
        enabled: root.interactionEnabled
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.selected()
    }
}
