import QtQuick

Rectangle {
    id: root
    required property var chrome
    required property string label
    property bool primary: false
    property bool destructive: false
    signal clicked()

    height: 45
    radius: 16
    antialiasing: true
    scale: hover.pressed ? 0.992 : 1
    color: !enabled
        ? chrome.theme.alpha(
            chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.58),
            0.30
        )
        : primary
            ? chrome.theme.alpha(chrome.accent, 0.64)
            : chrome.theme.alpha(
                chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56),
                0.47
            )
    border.width: 1
    border.color: primary
        ? chrome.theme.alpha(chrome.accent, 0.15)
        : chrome.theme.alpha(
            destructive ? chrome.theme.error : chrome.theme.foreground,
            destructive ? 0.075 : 0.050
        )
    opacity: enabled ? 1 : 0.46

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        antialiasing: true
        gradient: Gradient {
            GradientStop {
                position: 0
                color: chrome.theme.alpha(chrome.theme.foreground, root.primary ? 0.070 : 0.022)
            }
            GradientStop { position: 0.62; color: "transparent" }
            GradientStop {
                position: 1
                color: chrome.theme.alpha(
                    root.primary ? chrome.accent : chrome.theme.background,
                    root.primary ? 0.035 : 0.028
                )
            }
        }
    }

    Rectangle {
        id: hoverPlane
        anchors.fill: parent
        radius: parent.radius
        antialiasing: true
        color: root.primary
            ? chrome.theme.alpha(chrome.theme.foreground, 0.12)
            : chrome.theme.alpha(
                root.destructive ? chrome.theme.error : chrome.theme.foreground,
                root.destructive ? 0.09 : 0.07
            )
        opacity: root.enabled && hover.containsMouse ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.top: parent.top
        height: 1
        radius: 1
        antialiasing: true
        color: chrome.theme.alpha(chrome.theme.foreground, root.primary ? 0.10 : 0.045)
    }

    Text {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -1
        text: root.label
        color: root.destructive
            ? chrome.theme.error
            : root.primary
                ? Qt.rgba(1, 1, 1, 0.96)
                : chrome.textPrimary
        font.family: "Inter"
        font.pixelSize: 12
        font.weight: Font.DemiBold
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        renderType: Text.NativeRendering
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.clicked()
    }

    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
}
