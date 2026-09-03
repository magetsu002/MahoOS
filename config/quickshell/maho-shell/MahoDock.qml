import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    required property var theme
    required property var dockModel
    required property var dockState

    anchors {
        bottom: true
    }

    margins {
        bottom: 18
    }

    implicitWidth: Math.max(86, dockRow.implicitWidth + 24)
    implicitHeight: 72
    color: "transparent"
    visible: dockModel.items.length > 0
    aboveWindows: true
    focusable: false
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "maho-dock"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    readonly property color accent: stableAccent(theme.semanticAccent)
    readonly property bool brightBackdrop: theme.semanticBackground.hslLightness > 0.52
    readonly property color neutralMaterial:
        theme.mix(theme.semanticSurfaceElevated, theme.semanticBackground, 0.56)
    readonly property color shellMaterial:
        theme.mix(neutralMaterial, accent, 0.014)
    readonly property color shellFill:
        theme.alpha(shellMaterial, brightBackdrop ? 0.78 : 0.70)
    readonly property color shellRim:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.15 : 0.10)
    readonly property color shellSpecular:
        theme.alpha(theme.semanticForeground, brightBackdrop ? 0.11 : 0.075)
    readonly property color shellLowlight:
        theme.alpha(theme.semanticShadow, brightBackdrop ? 0.10 : 0.16)

    function stableAccent(source) {
        const saturation = source.hsvSaturation
        if (saturation < 0.08)
            return theme.mix(theme.semanticForeground, theme.semanticSurfaceElevated, 0.38)
        const hue = source.hsvHue < 0 ? 0 : source.hsvHue
        return Qt.hsva(
            hue,
            Math.max(0.18, Math.min(0.58, saturation)),
            Math.max(0.60, Math.min(0.86, source.hsvValue)),
            1
        )
    }

    mask: Region { item: dockShell }

    Rectangle {
        id: dockShell
        anchors.fill: parent
        radius: 27
        antialiasing: true
        color: root.shellFill
        border.width: 1
        border.color: root.shellRim
        clip: true

        // Keep every full-surface material layer radius-matched. Qt Quick clip
        // is rectangular, so unmatched gradient children would leak square
        // corners over the optical shell silhouette.
        Rectangle {
            anchors.fill: parent
            radius: dockShell.radius
            antialiasing: true
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.00
                    color: root.theme.alpha(root.theme.semanticForeground, 0.040)
                }
                GradientStop {
                    position: 0.24
                    color: root.theme.alpha(root.accent, 0.016)
                }
                GradientStop { position: 0.64; color: "transparent" }
                GradientStop {
                    position: 1.00
                    color: root.theme.alpha(root.theme.semanticShadow, root.brightBackdrop ? 0.055 : 0.10)
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 30
            anchors.rightMargin: 30
            anchors.top: parent.top
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellSpecular
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 34
            anchors.rightMargin: 34
            anchors.bottom: parent.bottom
            height: 1
            radius: 1
            antialiasing: true
            color: root.shellLowlight
        }

        Row {
            id: dockRow
            anchors.centerIn: parent
            spacing: 0

            Repeater {
                model: root.dockModel.items

                delegate: Item {
                    id: appCell
                    required property var modelData
                    required property int index

                    width: 62 + (modelData.breakBefore ? 13 : 0)
                    height: 62

                    property real hoverProgress: appMouse.containsMouse ? 1 : 0
                    property real pressProgress: appMouse.pressed ? 1 : 0

                    Behavior on hoverProgress {
                        NumberAnimation { duration: 155; easing.type: Easing.OutCubic }
                    }
                    Behavior on pressProgress {
                        NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
                    }

                    Item {
                        id: appTarget
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 62
                        height: 62

                        Rectangle {
                            id: focusMaterial
                            anchors.centerIn: parent
                            anchors.verticalCenterOffset: -2
                            width: 54
                            height: 54
                            radius: 19
                            antialiasing: true
                            color: root.theme.alpha(
                                root.theme.mix(
                                    root.theme.semanticSurfaceElevated,
                                    root.accent,
                                    modelData.focused ? 0.095 : 0.030
                                ),
                                modelData.focused ? 0.25 : 0.16
                            )
                            border.width: 1
                            border.color: root.theme.alpha(
                                modelData.focused ? root.accent : root.theme.semanticForeground,
                                modelData.focused ? 0.070 : 0.025
                            )
                            opacity: modelData.focused
                                ? 1
                                : appCell.hoverProgress * 0.82
                        }

                        Item {
                            id: iconLift
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 7 - appCell.hoverProgress * 2 + appCell.pressProgress * 1.5
                            width: 44
                            height: 44
                            scale: 1 + appCell.hoverProgress * 0.026 - appCell.pressProgress * 0.045

                            MahoDockAppIcon {
                                anchors.fill: parent
                                name: String(modelData.name || "")
                                entryId: String(modelData.id || "")
                                icon: String(modelData.icon || "")
                                iconPath: String(modelData.iconPath || "")
                            }
                        }

                        Rectangle {
                            id: runningShelf
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 2
                            width: modelData.focused ? 30
                                : modelData.running ? (modelData.windowCount > 1 ? 12 : 7)
                                : modelData.launching ? 9 : 0
                            height: modelData.focused ? 2.5 : 2
                            radius: 2
                            antialiasing: true
                            color: modelData.focused
                                ? root.theme.alpha(root.accent, 0.88)
                                : root.theme.alpha(root.theme.semanticForeground, modelData.onOtherWorkspace ? 0.32 : 0.58)
                            opacity: modelData.running || modelData.focused ? 1 : (modelData.launching ? 0.72 : 0)

                            Behavior on width {
                                NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
                            }
                            Behavior on color {
                                ColorAnimation { duration: 180; easing.type: Easing.OutCubic }
                            }
                            Behavior on opacity {
                                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
                            }
                        }

                        Rectangle {
                            visible: modelData.running && modelData.windowCount > 1
                            anchors.left: runningShelf.right
                            anchors.leftMargin: 3
                            anchors.verticalCenter: runningShelf.verticalCenter
                            width: 3
                            height: 3
                            radius: 2
                            antialiasing: true
                            color: root.theme.alpha(
                                modelData.focused ? root.accent : root.theme.semanticForeground,
                                modelData.onOtherWorkspace ? 0.30 : 0.52
                            )
                        }

                        Rectangle {
                            id: launchPulse
                            visible: modelData.launching && !modelData.running
                            anchors.centerIn: runningShelf
                            width: 10
                            height: 2
                            radius: 1
                            color: root.theme.alpha(root.accent, 0.78)
                            opacity: 0.74

                            SequentialAnimation on opacity {
                                running: launchPulse.visible
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.28; duration: 520; easing.type: Easing.InOutSine }
                                NumberAnimation { to: 0.82; duration: 520; easing.type: Easing.InOutSine }
                            }
                        }

                        MouseArea {
                            id: appMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.LeftButton | Qt.MiddleButton
                            cursorShape: Qt.PointingHandCursor
                            onClicked: function(mouse) {
                                root.dockModel.activateItem(modelData, mouse.button === Qt.MiddleButton)
                            }
                        }
                    }
                }
            }
        }
    }
}
