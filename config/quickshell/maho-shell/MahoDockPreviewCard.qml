import QtQuick
import Quickshell.Wayland

Item {
    id: root

    required property var theme
    required property color accent
    required property var windowData
    property bool active: false
    property bool hovered: hoverHandler.hovered

    signal activated(var windowData)

    width: 198
    height: 132

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: 16
        antialiasing: true
        color: root.theme.alpha(
            root.theme.mix(root.theme.semanticSurfaceElevated, root.theme.semanticBackground, 0.50),
            root.hovered ? 0.60 : 0.48
        )
        border.width: 1
        border.color: root.theme.alpha(
            root.hovered ? root.accent : root.theme.semanticForeground,
            root.hovered ? 0.24 : 0.11
        )
        clip: true

        Behavior on color {
            ColorAnimation { duration: 190; easing.type: Easing.OutCubic }
        }
        Behavior on border.color {
            ColorAnimation { duration: 190; easing.type: Easing.OutCubic }
        }

        ScreencopyView {
            id: capture
            anchors.fill: parent
            anchors.margins: 1
            captureSource: root.windowData && root.windowData.toplevel
                ? root.windowData.toplevel.wayland
                : null
            live: root.active && captureSource !== null
            paintCursor: false
            constraintSize: Qt.size(width, height)
            opacity: hasContent ? 0.96 : 0

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
            }
        }

        Rectangle {
            anchors.fill: parent
            radius: frame.radius
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.0
                    color: root.theme.alpha(root.theme.semanticForeground, 0.055)
                }
                GradientStop { position: 0.34; color: "transparent" }
                GradientStop {
                    position: 1.0
                    color: root.theme.alpha(root.theme.semanticShadow, 0.16)
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 34
            color: root.theme.alpha(root.theme.semanticShadow, 0.46)

            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                text: root.windowData ? String(root.windowData.title || "Window") : "Window"
                color: root.theme.semanticForeground
                font.pixelSize: 11
                font.weight: Font.Medium
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 14
            anchors.rightMargin: 14
            height: 1
            color: root.theme.alpha(root.theme.semanticForeground, 0.12)
        }
    }

    HoverHandler {
        id: hoverHandler
        cursorShape: Qt.PointingHandCursor
    }

    TapHandler {
        acceptedButtons: Qt.LeftButton
        onTapped: root.activated(root.windowData)
    }

    scale: root.hovered ? 1.015 : 1
    y: root.hovered ? -2 : 0

    Behavior on scale {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }
    Behavior on y {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }
}
