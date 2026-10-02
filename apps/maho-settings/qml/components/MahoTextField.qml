import QtQuick
import QtQuick.Controls

TextField {
    id: root

    property color surface: "#302b2b"
    property color foreground: "#f4eeee"
    property color muted: "#aaa3a3"
    property color accent: "#d8aaaa"

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 12
    topPadding: 0
    bottomPadding: 0
    selectByMouse: true
    color: root.foreground
    placeholderTextColor: Qt.rgba(root.muted.r, root.muted.g, root.muted.b, 0.72)
    font.pixelSize: 12

    background: Rectangle {
        radius: 11
        color: Qt.rgba(root.surface.r, root.surface.g, root.surface.b, root.hovered ? 0.78 : 0.62)
        border.width: 1
        border.color: root.activeFocus
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.32)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.075)
    }
}
