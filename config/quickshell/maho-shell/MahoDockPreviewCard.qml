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
    property real cardWidth: 198
    property real cardHeight: 138

    signal activated(var windowData)

    width: cardWidth
    height: cardHeight

    readonly property bool windowFocused:
        root.windowData ? Boolean(root.windowData.activated) : false

    readonly property var captureHandle: {
        if (!root.windowData || !root.windowData.toplevel)
            return null
        const top = root.windowData.toplevel
        return top.handle || top.wayland || null
    }

    Rectangle {
        id: frame
        anchors.fill: parent
        radius: Math.min(20, Math.max(14, root.height * 0.10))
        antialiasing: true
        color: root.theme.alpha(
            root.theme.mix(root.theme.semanticSurfaceElevated, root.theme.semanticBackground, 0.48),
            root.hovered ? 0.58 : 0.48
        )
        border.width: 1
        border.color: root.theme.alpha(
            root.windowFocused ? root.accent
                : (root.hovered ? root.theme.semanticForeground : root.theme.semanticForeground),
            root.windowFocused ? 0.42 : (root.hovered ? 0.20 : 0.11)
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
            color: root.theme.alpha(root.theme.semanticShadow, 0.16)
        }

        Rectangle {
            id: previewViewport
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: titleRail.top
            anchors.margins: 4
            anchors.bottomMargin: 3
            radius: Math.max(10, frame.radius - 5)
            color: root.theme.alpha(root.theme.semanticShadow, 0.24)
            clip: true

            ScreencopyView {
                id: capture
                anchors.fill: parent
                captureSource: root.captureHandle
                live: root.active && captureSource !== null
                paintCursor: false
                constraintSize: Qt.size(width, height)
                opacity: hasContent ? 1 : 0

                Behavior on opacity {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }
            }

            Item {
                anchors.fill: parent
                visible: !capture.hasContent
                opacity: capture.hasContent ? 0 : 1

                Rectangle {
                    anchors.fill: parent
                    radius: previewViewport.radius
                    color: root.theme.alpha(
                        root.theme.mix(root.theme.semanticSurfaceElevated, root.theme.semanticShadow, 0.36),
                        0.78
                    )
                }

                Rectangle {
                    anchors.fill: parent
                    radius: previewViewport.radius
                    color: "transparent"
                    gradient: Gradient {
                        GradientStop {
                            position: 0.0
                            color: root.theme.alpha(root.theme.semanticForeground, 0.060)
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
                    anchors.verticalCenterOffset: -8
                    width: Math.min(52, Math.max(38, root.height * 0.25))
                    height: width
                    name: root.appName
                    entryId: root.appEntryId
                    icon: root.appIcon
                    iconPath: root.appIconPath
                    opacity: 0.92
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 12
                    text: "Preview unavailable"
                    color: root.theme.semanticForegroundMuted
                    opacity: 0.60
                    font.pixelSize: 9
                    font.weight: Font.Medium
                }
            }

            Rectangle {
                anchors.fill: parent
                radius: previewViewport.radius
                color: "transparent"
                gradient: Gradient {
                    GradientStop {
                        position: 0.0
                        color: root.theme.alpha(root.theme.semanticForeground, 0.045)
                    }
                    GradientStop { position: 0.28; color: "transparent" }
                    GradientStop {
                        position: 1.0
                        color: root.theme.alpha(root.theme.semanticShadow, 0.085)
                    }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.leftMargin: 16
                anchors.rightMargin: 16
                height: 1
                color: root.theme.alpha(root.theme.semanticForeground, 0.13)
            }
        }

        Rectangle {
            id: titleRail
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 4
            anchors.rightMargin: 4
            anchors.bottomMargin: 4
            height: Math.min(36, Math.max(30, root.height * 0.19))
            radius: Math.max(9, frame.radius - 6)
            color: root.theme.alpha(
                root.theme.mix(root.theme.semanticSurfaceElevated, root.theme.semanticShadow, 0.34),
                capture.hasContent ? 0.76 : 0.62
            )
            border.width: 1
            border.color: root.theme.alpha(root.theme.semanticForeground, 0.050)

            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                text: root.windowData ? String(root.windowData.title || "Window") : "Window"
                color: root.theme.semanticForeground
                font.pixelSize: root.width > 300 ? 11 : 10
                font.weight: Font.Medium
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }

        Rectangle {
            visible: root.windowFocused
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            width: Math.min(38, parent.width * 0.18)
            height: 2
            radius: 1
            color: root.theme.alpha(root.accent, 0.88)
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

    scale: root.hovered ? 1.006 : 1
    y: root.hovered ? -1 : 0

    Behavior on scale {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }
    Behavior on y {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }
}
