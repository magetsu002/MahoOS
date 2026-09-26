import QtQuick
import QtQuick.Controls

ScrollBar {
    id: control

    required property var theme

    z: 100
    interactive: true
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    policy: ScrollBar.AsNeeded
    snapMode: ScrollBar.NoSnap
    minimumSize: 0.0
    implicitWidth: 10
    padding: 2

    background: Rectangle {
        implicitWidth: 8
        radius: width / 2
        color: theme.alpha(theme.foreground, 0.038)
        opacity: control.hovered || control.pressed ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }

    contentItem: Rectangle {
        implicitWidth: 5
        radius: width / 2
        color: control.pressed
            ? theme.alpha(theme.accent, 0.72)
            : (control.hovered
                ? theme.alpha(theme.accent, 0.46)
                : theme.alpha(theme.foreground, 0.28))
        opacity: control.active || control.hovered || control.pressed ? 1 : 0.70

        Behavior on color {
            ColorAnimation { duration: 90; easing.type: Easing.OutCubic }
        }
        Behavior on opacity {
            NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }
}
