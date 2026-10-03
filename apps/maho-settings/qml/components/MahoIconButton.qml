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

    implicitWidth: 32
    implicitHeight: 32
    padding: 0
    hoverEnabled: true

    contentItem: MahoIcon {
        width: 16
        height: 16
        anchors.centerIn: parent
        name: root.iconName
        tone: root.enabled
            ? (root.hovered || root.emphasized ? root.foreground : root.muted)
            : Qt.rgba(root.muted.r, root.muted.g, root.muted.b, 0.48)
        opacity: root.enabled ? 1 : 0.68
    }

    background: Rectangle {
        radius: 10
        color: root.down
            ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
            : root.hovered
                ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.065)
                : root.emphasized
                    ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.10)
                    : "transparent"
        border.width: root.emphasized ? 1 : 0
        border.color: root.emphasized
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.24)
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
            leftPadding: 3
            rightPadding: 3
        }

        background: Rectangle {
            radius: 8
            color: Qt.rgba(
                root.muted.r * 0.18,
                root.muted.g * 0.18,
                root.muted.b * 0.18,
                0.96
            )
            border.width: 1
            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
        }
    }
}
