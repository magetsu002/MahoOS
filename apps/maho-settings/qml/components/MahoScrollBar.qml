import QtQuick
import QtQuick.Controls

ScrollBar {
    id: root

    property color foreground: "#f3eef8"
    property bool reducedMotion: false

    policy: ScrollBar.AsNeeded
    interactive: true
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    implicitWidth: 9
    padding: 2

    background: Rectangle {
        implicitWidth: 7
        radius: width / 2
        color: "transparent"
    }

    contentItem: Rectangle {
        implicitWidth: 4
        radius: width / 2
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b,
                       root.pressed ? 0.42 : root.hovered ? 0.30 : 0.18)
        opacity: root.size < 1.0 ? 1.0 : 0.0

        Behavior on color { ColorAnimation { duration: root.reducedMotion ? 0 : 90 } }
        Behavior on opacity { NumberAnimation { duration: root.reducedMotion ? 0 : 100 } }
    }
}
