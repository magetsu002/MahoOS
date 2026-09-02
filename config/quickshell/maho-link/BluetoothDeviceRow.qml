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
        anchors.fill: parent
        anchors.margins: 3
        radius: 13
        color: rowHover.pressed
            ? chrome.theme.alpha(chrome.accent, 0.085)
            : rowHover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.045)
                : "transparent"

        Behavior on color { ColorAnimation { duration: 115 } }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        width: 34
        height: 34
        radius: 12
        color: chrome.theme.alpha(
            chrome.mix(
                chrome.theme.surfaceHigh,
                device.connected ? chrome.accent : chrome.theme.background,
                device.connected ? 0.12 : 0.18
            ),
            0.72
        )
        border.width: 1
        border.color: chrome.theme.alpha(
            device.connected ? chrome.accent : chrome.theme.foreground,
            device.connected ? 0.12 : 0.045
        )

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            height: 1
            color: chrome.theme.alpha(chrome.theme.foreground, 0.055)
        }

        Text {
            anchors.centerIn: parent
            text: root.glyph(device.kind)
            color: device.connected ? chrome.accent : chrome.theme.alpha(chrome.textSecondary, 0.88)
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 18
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
                ? chrome.theme.alpha(chrome.accent, 0.82)
                : chrome.theme.alpha(chrome.textSecondary, 0.68)
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
            radius: 11
            color: actionHover.pressed
                ? chrome.theme.alpha(chrome.accent, 0.15)
                : actionHover.containsMouse
                    ? chrome.theme.alpha(chrome.accent, 0.11)
                    : chrome.theme.alpha(chrome.theme.surfaceHigh, 0.46)
            border.width: 1
            border.color: actionHover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.15)
                : chrome.theme.alpha(chrome.theme.foreground, 0.045)

            Behavior on color { ColorAnimation { duration: 115 } }
            Behavior on border.color { ColorAnimation { duration: 115 } }

            Text {
                anchors.centerIn: parent
                text: root.actionLabel
                color: root.actionLabel !== "" ? chrome.accent : chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
        }

        Text {
            anchors.centerIn: parent
            visible: root.actionLabel === ""
            text: "›"
            color: rowHover.containsMouse
                ? chrome.theme.alpha(chrome.textPrimary, 0.82)
                : chrome.theme.alpha(chrome.textSecondary, 0.68)
            font.family: "Inter"
            font.pixelSize: 22
            font.weight: Font.Light

            Behavior on color { ColorAnimation { duration: 115 } }
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
