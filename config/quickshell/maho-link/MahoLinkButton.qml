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
    color: !enabled
        ? chrome.theme.alpha(
            chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.58),
            0.30
        )
        : primary
            ? chrome.theme.alpha(chrome.accent, hover.containsMouse ? 0.72 : 0.64)
            : hover.pressed
                ? chrome.theme.alpha(chrome.theme.foreground, 0.055)
                : hover.containsMouse
                    ? chrome.theme.alpha(chrome.theme.foreground, 0.030)
                    : chrome.theme.alpha(
                        chrome.mix(chrome.theme.surfaceHigh, chrome.theme.background, 0.56),
                        0.47
                    )
    border.width: 1
    border.color: primary
        ? chrome.theme.alpha(chrome.accent, hover.containsMouse ? 0.20 : 0.15)
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
        text: root.label
        color: root.destructive
            ? chrome.theme.error
            : root.primary
                ? Qt.rgba(1, 1, 1, 0.96)
                : chrome.textPrimary
        font.family: "Inter"
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }

    MouseArea {
        id: hover
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.clicked()
    }

    Behavior on color { ColorAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 120 } }
}
