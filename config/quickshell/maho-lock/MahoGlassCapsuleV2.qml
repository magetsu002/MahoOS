import QtQuick

Rectangle {
    id: root

    required property var theme
    property bool focused: false
    property bool strong: false
    property bool hovered: false

    readonly property real fillAlpha: strong
        ? (hovered ? 0.175 : 0.150)
        : (focused ? 0.125 : 0.095)

    readonly property color neutralWhite: Qt.rgba(1, 1, 1, 1)
    readonly property color materialTint: theme.mix(
        neutralWhite,
        theme.accent,
        focused ? 0.030 : 0.012
    )

    radius: height / 2
    color: theme.alpha(materialTint, fillAlpha)
    border.width: Math.max(1, height / 58)
    border.color: focused
        ? Qt.rgba(1, 1, 1, 0.265)
        : Qt.rgba(1, 1, 1, strong ? 0.155 : 0.145)

    Behavior on color {
        ColorAnimation { duration: 125 }
    }

    Behavior on border.color {
        ColorAnimation { duration: 125 }
    }

    // One restrained inner edge gives the shell definition without drawing a
    // fake glossy gradient across the whole control.
    Rectangle {
        anchors.fill: parent
        anchors.margins: Math.max(1, root.height / 58)
        radius: Math.max(0, root.radius - 1)
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, root.focused ? 0.080 : 0.045)
    }

    // Soft reflected cap. It is intentionally faint and short so it reads as
    // material response rather than a painted highlight.
    Rectangle {
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 1
        width: Math.max(0, parent.width - parent.height * 0.88)
        height: 1
        radius: 1
        color: Qt.rgba(1, 1, 1, root.focused ? 0.105 : 0.065)
    }
}
