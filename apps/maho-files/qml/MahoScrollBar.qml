import QtQuick
import QtQuick.Controls

ScrollBar {
    id: control

    property color thumbColor: "#808080"
    property color thumbHoverColor: thumbColor
    property color thumbPressedColor: thumbHoverColor
    property color trackColor: "transparent"

    z: 80
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
        color: control.trackColor
        opacity: control.hovered || control.pressed ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }

    contentItem: Rectangle {
        implicitWidth: 5
        radius: width / 2
        color: control.pressed
            ? control.thumbPressedColor
            : control.hovered ? control.thumbHoverColor : control.thumbColor
        opacity: control.active || control.hovered || control.pressed ? 1 : 0.68

        Behavior on color {
            ColorAnimation { duration: 90; easing.type: Easing.OutCubic }
        }
        Behavior on opacity {
            NumberAnimation { duration: 110; easing.type: Easing.OutCubic }
        }
    }
}
