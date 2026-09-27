import QtQuick
import QtQuick.Controls

ScrollBar {
    id: control

    required property var theme
    property bool viewMoving: false
    property bool lingerVisible: false
    readonly property bool visualVisible:
        control.pressed || control.hovered || control.viewMoving || control.lingerVisible

    function beginActivity() {
        lingerVisible = true
        autoHideTimer.stop()
    }

    function endActivity() {
        if (!pressed && !hovered && !viewMoving)
            autoHideTimer.restart()
    }

    function noteActivity() {
        lingerVisible = true
        if (pressed || hovered || viewMoving)
            autoHideTimer.stop()
        else
            autoHideTimer.restart()
    }

    z: 100
    interactive: true
    hoverEnabled: true
    focusPolicy: Qt.NoFocus
    policy: ScrollBar.AsNeeded
    snapMode: ScrollBar.NoSnap
    minimumSize: 0.0
    implicitWidth: 10
    padding: 2

    Connections {
        target: control
        function onViewMovingChanged() {
            control.viewMoving ? control.beginActivity() : control.endActivity()
        }
        function onHoveredChanged() {
            control.hovered ? control.beginActivity() : control.endActivity()
        }
        function onPressedChanged() {
            control.pressed ? control.beginActivity() : control.endActivity()
        }
    }

    Timer {
        id: autoHideTimer
        interval: 700
        repeat: false
        onTriggered: control.lingerVisible = false
    }

    background: Rectangle {
        implicitWidth: 8
        radius: width / 2
        color: theme.alpha(theme.foreground, 0.038)
        opacity: control.pressed ? 1 : (control.hovered ? 0.72 : 0)

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
        opacity: control.visualVisible ? 1 : 0

        Behavior on color {
            ColorAnimation { duration: 90; easing.type: Easing.OutCubic }
        }
        Behavior on opacity {
            NumberAnimation {
                duration: control.visualVisible ? 55 : 180
                easing.type: Easing.OutCubic
            }
        }
    }
}
