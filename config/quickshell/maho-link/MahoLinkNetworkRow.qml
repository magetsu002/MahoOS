import QtQuick

Item {
    id: root
    required property var chrome
    required property var network
    property bool interactionEnabled: true
    signal selected()

    width: parent ? parent.width : 420
    height: 61

    Rectangle {
        anchors.fill: parent
        anchors.margins: 3
        radius: 13
        color: hover.containsMouse ? chrome.theme.alpha(chrome.accent, 0.07) : "transparent"
        Behavior on color { ColorAnimation { duration: 105 } }
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 17
        anchors.verticalCenter: parent.verticalCenter
        text: "󰖩"
        color: chrome.textSecondary
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 18
    }

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 53
        anchors.right: status.left
        anchors.rightMargin: 12
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2

        Text {
            width: parent.width
            text: String(root.network.ssid || "")
            color: chrome.textPrimary
            elide: Text.ElideRight
            font.family: "Inter"
            font.pixelSize: 14
            font.weight: Font.Medium
        }

        Text {
            visible: Boolean(root.network.enterprise)
            width: parent.width
            text: "Enterprise authentication"
            color: chrome.textSecondary
            elide: Text.ElideRight
            font.family: "Inter"
            font.pixelSize: 10
        }
    }

    Row {
        id: status
        anchors.right: parent.right
        anchors.rightMargin: 15
        anchors.verticalCenter: parent.verticalCenter
        spacing: 10

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: Boolean(root.network.secured)
            text: ""
            color: chrome.textSecondary
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 12
        }

        MahoLinkSignal {
            anchors.verticalCenter: parent.verticalCenter
            chrome: root.chrome
            strength: Number(root.network.signal || 0)
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "›"
            color: chrome.textSecondary
            font.family: "Inter"
            font.pixelSize: 20
        }
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        enabled: root.interactionEnabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.selected()
    }
}
