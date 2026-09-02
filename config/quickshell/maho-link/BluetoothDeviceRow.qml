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
        color: rowHover.containsMouse
            ? chrome.theme.alpha(chrome.accent, 0.055)
            : "transparent"

        Behavior on color { ColorAnimation { duration: 120 } }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 13
        anchors.verticalCenter: parent.verticalCenter
        width: 34
        height: 34
        radius: 12
        color: chrome.theme.alpha(
            device.connected ? chrome.accent : chrome.textSecondary,
            device.connected ? 0.13 : 0.075
        )

        Text {
            anchors.centerIn: parent
            text: root.glyph(device.kind)
            color: device.connected ? chrome.accent : chrome.textSecondary
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
            color: chrome.theme.alpha(chrome.textSecondary, 0.76)
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
        width: root.actionLabel !== "" ? 72 : 28
        height: 34

        Rectangle {
            anchors.fill: parent
            visible: root.actionLabel !== ""
            radius: 11
            color: actionHover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.14)
                : chrome.theme.alpha(chrome.textSecondary, 0.07)
            border.width: 1
            border.color: chrome.theme.alpha(chrome.theme.outline, 0.07)

            Text {
                anchors.centerIn: parent
                text: root.actionLabel
                color: chrome.textPrimary
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }
        }

        Text {
            anchors.centerIn: parent
            visible: root.actionLabel === ""
            text: "›"
            color: chrome.theme.alpha(chrome.textSecondary, 0.82)
            font.family: "Inter"
            font.pixelSize: 23
            font.weight: Font.Light
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
