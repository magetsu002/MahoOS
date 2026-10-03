import QtQuick

Item {
    id: root
    required property var chrome
    required property var network
    property bool interactionEnabled: true
    readonly property bool forgettable:
        Boolean(network.saved)
        && !Boolean(network.active)
        && String(network.profileUuid || "") !== ""
    signal selected()
    signal forgetRequested()

    width: parent ? parent.width : 420
    height: 58

    Rectangle {
        id: rowHoverPlane
        anchors.fill: parent
        anchors.margins: 3
        radius: 15
        antialiasing: true
        color: chrome.theme.alpha(chrome.theme.foreground, 0.030)
        opacity: hover.containsMouse || hover.activeFocus ? 1 : 0

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
                || Boolean(root.network.active)
                || (Boolean(root.network.saved) && root.network.available === false)
            width: parent.width
            text: Boolean(root.network.active)
                ? "Current · Saved"
                : Boolean(root.network.enterprise)
                    ? (root.network.available === false ? "Enterprise · Saved" : "Enterprise authentication")
                    : "Saved network"
            color: chrome.theme.alpha(chrome.textSecondary, 0.62)
            elide: Text.ElideRight
            font.family: "Inter"
            font.pixelSize: 9
        }
    }

    Row {
        id: status
        anchors.right: forgetButton.visible ? forgetButton.left : parent.right
        anchors.rightMargin: forgetButton.visible ? 4 : 15
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
            visible: root.network.available !== false
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

    Item {
        id: forgetButton
        z: 3
        anchors.right: parent.right
        anchors.rightMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        visible: root.forgettable
        width: visible ? 54 : 0
        height: 28

        Text {
            id: forgetGlow
            anchors.centerIn: parent
            text: "Forget"
            color: chrome.theme.alpha(chrome.theme.error, 0.62)
            opacity: forgetHover.containsMouse || forgetHover.activeFocus ? 0.48 : 0
            scale: 1.08
            font.family: "Inter"
            font.pixelSize: 9
            font.weight: Font.Medium

            Behavior on opacity {
                NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
            }
        }

        Text {
            anchors.centerIn: parent
            text: "Forget"
            color: chrome.theme.alpha(
                chrome.theme.error,
                forgetHover.containsMouse || forgetHover.activeFocus ? 1.0 : 0.84
            )
            font.family: "Inter"
            font.pixelSize: 9
            font.weight: forgetHover.containsMouse || forgetHover.activeFocus
                ? Font.DemiBold : Font.Medium

            Behavior on color {
                ColorAnimation { duration: 110 }
            }
        }

        MouseArea {
            id: forgetHover
            anchors.fill: parent
            enabled: root.interactionEnabled
            hoverEnabled: true
            activeFocusOnTab: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: root.forgetRequested()
            Keys.onReturnPressed: root.forgetRequested()
            Keys.onSpacePressed: root.forgetRequested()
        }
    }

    MouseArea {
        id: hover
        z: 1
        anchors.fill: parent
        enabled: root.interactionEnabled
        hoverEnabled: true
        activeFocusOnTab: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.selected()
        Keys.onReturnPressed: root.selected()
        Keys.onSpacePressed: root.selected()
    }
}
