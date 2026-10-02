import QtQuick
import QtQuick.Controls

Switch {
    id: root

    property color accent: "#d0bcff"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property bool reducedMotion: false

    // Backend state owns checked. Keeping the control non-checkable prevents a
    // click from destroying the QML binding before the verified readback lands.
    checkable: false
    signal toggleRequested(bool value)

    implicitWidth: 46
    implicitHeight: 26
    padding: 0
    opacity: root.enabled ? 1.0 : 0.46

    onClicked: root.toggleRequested(!root.checked)

    indicator: Rectangle {
        implicitWidth: 44
        implicitHeight: 24
        radius: 12
        color: root.checked
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.34)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
        border.width: 1
        border.color: root.checked
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.48)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.085)

        Rectangle {
            width: 18
            height: 18
            radius: 9
            y: 3
            x: root.checked ? parent.width - width - 3 : 3
            color: root.checked ? root.accent : root.muted
            Behavior on x {
                NumberAnimation { duration: root.reducedMotion ? 0 : 120 }
            }
        }
    }

    contentItem: Item {}
}
