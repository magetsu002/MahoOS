import QtQuick
import QtQuick.Controls

Button {
    id: root

    property string iconName: ""
    property string label: ""
    property color accent: "#d0bcff"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property bool emphasized: false

    implicitWidth: 28
    implicitHeight: 28
    padding: 0
    hoverEnabled: true

    contentItem: MahoActionGlyph {
        width: 14
        height: 14
        anchors.centerIn: parent
        name: root.iconName
        tone: !root.enabled
            ? Qt.rgba(root.muted.r, root.muted.g, root.muted.b, 0.42)
            : root.emphasized
                ? root.accent
                : root.hovered
                    ? root.foreground
                    : root.muted
        opacity: root.enabled ? 1 : 0.62
    }

    background: Rectangle {
        radius: 7
        color: root.down
            ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
            : root.hovered
                ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.055)
                : "transparent"
    }

    ToolTip {
        visible: root.hovered && root.label.length > 0
        delay: 420
        timeout: 2400
        text: root.label

        contentItem: Text {
            text: root.label
            color: root.foreground
            font.pixelSize: 11
            leftPadding: 4
            rightPadding: 4
        }

        background: Rectangle {
            radius: 7
            color: Qt.rgba(
                root.muted.r * 0.17,
                root.muted.g * 0.17,
                root.muted.b * 0.17,
                0.97
            )
            border.width: 1
            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
        }
    }
}
