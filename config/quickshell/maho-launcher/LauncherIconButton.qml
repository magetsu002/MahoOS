import QtQuick
import Quickshell
import Quickshell.Widgets

Rectangle {
    id: root

    required property var theme
    property string symbol: "grid"
    property string iconName: "application-x-executable"
    property bool emphasized: false

    signal activated()

    readonly property bool hovered: hover.hovered
    readonly property bool pressed: tap.pressed

    width: 40
    height: 40
    radius: 12
    color: pressed
        ? theme.controlPressed
        : (hovered ? theme.controlHover : theme.controlFill)
    border.width: 1
    border.color: emphasized ? theme.controlRimActive : theme.controlRim
    scale: pressed ? 0.92 : (hovered ? 1.045 : 1)

    Behavior on color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 165; easing.type: Easing.OutBack } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: root.radius - 1
        color: "transparent"
        border.width: 1
        border.color: theme.controlInnerRim
        opacity: root.hovered ? 1 : 0.72
        Behavior on opacity { NumberAnimation { duration: 140 } }
    }

    Item {
        id: glyphLayer
        anchors.centerIn: parent
        width: 22
        height: 22
        scale: root.pressed ? 0.88 : (root.hovered ? 1.04 : 1)
        rotation: root.symbol === "controls" && root.hovered ? 1.5 : 0

        Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutBack } }
        Behavior on rotation { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }

        Item {
            anchors.fill: parent
            visible: root.symbol === "grid"

            Repeater {
                model: 9
                Rectangle {
                    required property int index
                    width: 3.2
                    height: 3.2
                    radius: 1.6
                    x: 3 + (index % 3) * 6.4
                    y: 3 + Math.floor(index / 3) * 6.4
                    color: root.theme.controlGlyph
                    opacity: root.hovered ? 1 : 0.84
                    scale: root.hovered ? 1.06 : 1
                    Behavior on opacity { NumberAnimation { duration: 140 } }
                    Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                }
            }
        }

        Item {
            anchors.fill: parent
            visible: root.symbol === "controls"

            Repeater {
                model: 3
                Item {
                    required property int index
                    width: 20
                    height: 5
                    x: 1
                    y: 2 + index * 7

                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        height: 1.4
                        radius: 0.7
                        color: root.theme.controlGlyph
                        opacity: root.hovered ? 0.96 : 0.78
                    }

                    Rectangle {
                        width: 5
                        height: 5
                        radius: 2.5
                        y: 0
                        x: {
                            if (parent.index === 0)
                                return root.hovered ? 11 : 9
                            if (parent.index === 1)
                                return root.hovered ? 4 : 6
                            return root.hovered ? 9 : 11
                        }
                        color: root.theme.controlGlyph
                        Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    }
                }
            }
        }

        IconImage {
            anchors.centerIn: parent
            width: 18
            height: 18
            visible: root.symbol !== "grid" && root.symbol !== "controls"
            source: Quickshell.iconPath(root.iconName, "application-x-executable")
            asynchronous: true
            mipmap: true
            opacity: root.hovered ? 1 : 0.86
        }
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.activated()
    }
}
