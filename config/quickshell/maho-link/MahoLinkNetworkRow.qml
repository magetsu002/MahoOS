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
        anchors.fill: parent
        anchors.margins: 3
        radius: 15
        antialiasing: true
        color: hover.pressed
            ? chrome.theme.alpha(chrome.theme.foreground, 0.052)
            : hover.containsMouse
                ? chrome.theme.alpha(chrome.theme.foreground, 0.028)
                : "transparent"
        Behavior on color { ColorAnimation { duration: 130; easing.type: Easing.OutCubic } }
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
        scale: hover.containsMouse ? 1.018 : 1
        color: chrome.theme.alpha(
            chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.44),
            0.40
        )
        border.width: 1
        border.color: chrome.theme.alpha(chrome.theme.foreground, 0.040)

        Behavior on scale { NumberAnimation { duration: 135; easing.type: Easing.OutCubic } }

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
            glyphColor: hover.containsMouse
                ? chrome.theme.alpha(chrome.accent, 0.84)
                : chrome.theme.alpha(chrome.textSecondary, 0.78)

            Behavior on glyphColor {
                ColorAnimation { duration: 125; easing.type: Easing.OutCubic }
            }
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
            color: hover.containsMouse
                ? chrome.theme.alpha(chrome.textPrimary, 0.76)
                : chrome.theme.alpha(chrome.textSecondary, 0.56)
            font.family: "Inter"
            font.pixelSize: 20
            font.weight: Font.Light
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            renderType: Text.NativeRendering
            Behavior on color { ColorAnimation { duration: 125; easing.type: Easing.OutCubic } }
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
