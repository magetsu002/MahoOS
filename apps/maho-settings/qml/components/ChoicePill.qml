import QtQuick
import QtQuick.Controls

Button {
    id: root
    property color accent: "#d0bcff"
    property color surface: "#312e37"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property bool selected: false

    implicitHeight: 36
    leftPadding: 14
    rightPadding: 14
    hoverEnabled: true

    contentItem: Text {
        text: root.text
        color: root.enabled ? (root.selected ? root.accent : root.foreground) : root.muted
        font.pixelSize: 12
        font.weight: root.selected ? Font.DemiBold : Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }

    background: Rectangle {
        radius: 11
        color: root.down
            ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
            : root.selected
                ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.14)
                : (root.hovered ? Qt.lighter(root.surface, 1.08) : root.surface)
        border.width: 1
        border.color: root.selected
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.48)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
    }
}
