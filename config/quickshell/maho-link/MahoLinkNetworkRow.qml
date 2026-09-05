import QtQuick

Item {
    id: root
    required property var chrome
    required property var network
    property bool interactionEnabled: true
    signal selected()

    width: parent ? parent.width : 420
    height: 58

    Rectangle {
        id: rowHoverPlane
        anchors.fill: parent
        anchors.margins: 3
        radius: 15
        antialiasing: true
        color: chrome.theme.alpha(chrome.theme.foreground, 0.030)
        opacity: hover.containsMouse ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        id: networkIcon
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        width: 32
        height: 32
        radius: 12
        antialiasing: true
        color: chrome.theme.alpha(
            chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.44),
            0.40
        )
        border.width: 1
        border.color: chrome.theme.alpha(chrome.theme.foreground, 0.040)

        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            antialiasing: true
            gradient: Gradient {
                GradientStop { position: 0; color: chrome.theme.alpha(chrome.theme.foreground, 0.030) }
                GradientStop { position: 0.62; color: "transparent" }
                GradientStop { position: 1; color: chrome.theme.alpha(chrome.theme.background, 0.026) }
            }
        }

        MahoWifiGlyph {
            anchors.centerIn: parent
            width: 18
            height: 18
            glyphColor: chrome.theme.alpha(chrome.textSecondary, 0.78)
        }
    }

    Column {
        anchors.left: parent.left
        anchors.leftMargin: 58
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
            font.pixelSize: 13
            font.weight: Font.Medium
        }

        Text {
            visible: Boolean(root.network.enterprise)
            width: parent.width
            text: "Enterprise authentication"
            color: chrome.theme.alpha(chrome.textSecondary, 0.62)
            elide: Text.ElideRight
            font.family: "Inter"
            font.pixelSize: 9
        }
    }

    Row {
        id: status
        anchors.right: parent.right
        anchors.rightMargin: 15
        anchors.verticalCenter: parent.verticalCenter
        spacing: 9

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -1
            visible: Boolean(root.network.secured)
            text: ""
            color: chrome.theme.alpha(chrome.textSecondary, 0.68)
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 11
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            renderType: Text.NativeRendering
        }

        MahoLinkSignal {
            anchors.verticalCenter: parent.verticalCenter
            chrome: root.chrome
            strength: Number(root.network.signal || 0)
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -1
            text: "›"
            color: chrome.theme.alpha(chrome.textSecondary, 0.60)
            font.family: "Inter"
            font.pixelSize: 20
            font.weight: Font.Light
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            renderType: Text.NativeRendering
        }
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        enabled: root.interactionEnabled
        hoverEnabled: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.selected()
    }
}
