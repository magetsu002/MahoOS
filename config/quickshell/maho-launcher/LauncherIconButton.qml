import QtQuick
import Quickshell
import Quickshell.Widgets

Rectangle {
    id: root

    required property var theme
    property string iconName: "application-x-executable"
    property string tooltip: ""
    property bool emphasized: false
    property real hoverRotation: 0

    signal activated()

    readonly property bool hovered: hover.hovered
    readonly property bool pressed: tap.pressed

    width: 38
    height: 38
    radius: 11
    color: pressed
        ? theme.controlPressed
        : (hovered ? theme.controlHover : theme.controlFill)
    border.width: 1
    border.color: emphasized
        ? theme.alpha(theme.accent, hovered ? 0.34 : 0.22)
        : theme.controlRim
    scale: pressed ? 0.92 : (hovered ? 1.035 : 1)

    Behavior on color { ColorAnimation { duration: 150; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 140 } }
    Behavior on scale { NumberAnimation { duration: 155; easing.type: Easing.OutBack } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: root.radius - 1
        color: "transparent"
        border.width: 1
        border.color: theme.alpha(theme.foreground, root.hovered ? 0.030 : 0.016)
    }

    IconImage {
        anchors.centerIn: parent
        width: 18
        height: 18
        source: Quickshell.iconPath(root.iconName, true)
        asynchronous: true
        mipmap: true
        opacity: root.pressed ? 0.78 : (root.hovered ? 1 : 0.84)
        rotation: root.hovered ? root.hoverRotation : 0
        scale: root.pressed ? 0.88 : 1

        Behavior on opacity { NumberAnimation { duration: 120 } }
        Behavior on rotation { NumberAnimation { duration: 210; easing.type: Easing.OutCubic } }
        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
    }

    HoverHandler { id: hover }

    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.activated()
    }
}
