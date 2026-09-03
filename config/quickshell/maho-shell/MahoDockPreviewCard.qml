import QtQuick
import Quickshell.Wayland

Item {
    id: root

    required property var theme
    required property color accent
    required property var windowData
    property string appName: "Application"
    property string appEntryId: ""
    property string appIcon: ""
    property string appIconPath: ""
    property bool active: false
    property bool hovered: hoverHandler.hovered

    signal activated(var windowData)

    width: 198
    height: 132

    readonly property var captureHandle: {
        if (!root.windowData || !root.windowData.toplevel)
            return null
        const top = root.windowData.toplevel
        return top.handle || top.wayland || null
    }

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: 16
        antialiasing: true
        color: root.theme.alpha(
            root.theme.mix(root.theme.semanticSurfaceElevated, root.theme.semanticBackground, 0.56),
            root.hovered ? 0.64 : 0.52
        )
        border.width: 1
        border.color: root.theme.alpha(
            root.hovered ? root.accent : root.theme.semanticForeground,
            root.hovered ? 0.25 : 0.12
        )
        clip: true

        Behavior on color {
            ColorAnimation { duration: 190; easing.type: Easing.OutCubic }
        }
        Behavior on border.color {
            ColorAnimation { duration: 190; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.fill: parent
            radius: frame.radius
            color: root.theme.alpha(root.theme.semanticShadow, 0.20)
        }

        ScreencopyView {
            id: capture
            anchors.fill: parent
            anchors.margins: 1
            captureSource: root.captureHandle
            live: root.active && captureSource !== null
            paintCursor: false
            constraintSize: Qt.size(width, height)
            opacity: hasContent ? 1 : 0

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
            }
        }

        // Capture protocols are compositor/runtime capabilities. Never present
        // an empty black rectangle as though a live preview succeeded.
        Item {
            anchors.fill: parent
            visible: !capture.hasContent
            opacity: capture.hasContent ? 0 : 1

            Rectangle {
                anchors.fill: parent
                radius: frame.radius
                color: root.theme.alpha(
                    root.theme.mix(root.theme.semanticSurfaceElevated, root.theme.semanticShadow, 0.42),
                    0.78
                )
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
                    GradientStop { position: 0.45; color: "transparent" }
                    GradientStop {
                        position: 1.0
                        color: root.theme.alpha(root.theme.semanticShadow, 0.18)
                    }
                }
            }

            MahoDockAppIcon {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -9
                width: 42
                height: 42
                name: root.appName
                entryId: root.appEntryId
                icon: root.appIcon
                iconPath: root.appIconPath
                opacity: 0.92
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 38
                text: "Preview unavailable"
                color: root.theme.semanticForegroundMuted
                opacity: 0.62
                font.pixelSize: 9
                font.weight: Font.Medium
            }
        }

        Rectangle {
            anchors.fill: parent
            radius: frame.radius
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.0
                    color: root.theme.alpha(root.theme.semanticForeground, 0.050)
                }
                GradientStop { position: 0.30; color: "transparent" }
                GradientStop {
                    position: 1.0
                    color: root.theme.alpha(root.theme.semanticShadow, 0.15)
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 34
            color: root.theme.alpha(root.theme.semanticShadow, capture.hasContent ? 0.50 : 0.34)

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
            color: root.theme.alpha(root.theme.semanticForeground, 0.15)
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

    scale: root.hovered ? 1.012 : 1
    y: root.hovered ? -2 : 0

    Behavior on scale {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }
    Behavior on y {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }
}
