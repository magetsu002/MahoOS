import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var palette
    readonly property var state: bridge && bridge.state.input ? bridge.state.input : ({})
    readonly property var current: state.current || ({})
    readonly property color foreground: palette ? palette.foreground : "#f3eef8"
    readonly property color muted: palette ? palette.muted : "#aaa3af"
    readonly property color accent: palette ? palette.accent : "#d0bcff"
    readonly property color surface: palette ? palette.surfaceElevated : "#2b2930"
    readonly property color borderColor: palette ? palette.border : "#3d3942"

    ScrollView {
        anchors.fill: parent
        clip: true

        ColumnLayout {
            width: Math.max(0, root.width - 14)
            spacing: 14

            PageHeader {
                title: "Keyboard & Pointer"
                subtitle: "Only controls with a real Hyprland backend are exposed. Current device identity comes from the compositor."
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Input state unavailable"
                detail: root.state.error || root.bridge.error
                retryVisible: true
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted
                accent: root.accent
                onRetryRequested: root.bridge.refresh()
            }

            SettingCard {
                visible: !!root.state.available
                title: "Detected devices"
                description: "Truthful compositor inventory; device-specific controls can be added without changing the page architecture."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Text {
                    Layout.fillWidth: true
                    text: "Keyboards: " + ((root.state.keyboards || []).join(", ") || "None")
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: "Mice: " + ((root.state.mice || []).join(", ") || "None")
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
                Text {
                    Layout.fillWidth: true
                    text: "Touchpads: " + ((root.state.touchpads || []).join(", ") || "None")
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Keyboard"
                description: "Repeat settings apply live and persist as user-owned session preferences."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Repeat rate"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    TextField {
                        id: repeatRate
                        Layout.preferredWidth: 100
                        text: Number(root.current.repeatRate || 25).toString()
                        validator: IntValidator { bottom: 1; top: 100 }
                        color: root.foreground
                        onEditingFinished: root.bridge.perform("input.set", { key: "repeatRate", value: Number(text) })
                        background: Rectangle {
                            radius: 10
                            color: root.surface
                            border.width: 1
                            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Repeat delay (ms)"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    TextField {
                        id: repeatDelay
                        Layout.preferredWidth: 100
                        text: Number(root.current.repeatDelay || 600).toString()
                        validator: IntValidator { bottom: 100; top: 2000 }
                        color: root.foreground
                        onEditingFinished: root.bridge.perform("input.set", { key: "repeatDelay", value: Number(text) })
                        background: Rectangle {
                            radius: 10
                            color: root.surface
                            border.width: 1
                            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Mouse"
                description: "Global pointer sensitivity. Unsupported acceleration profiles are intentionally not invented here."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Sensitivity"; color: root.foreground; font.pixelSize: 13 }
                    MahoSlider {
                        Layout.fillWidth: true
                        from: -1
                        to: 1
                        stepSize: 0.05
                        value: Number(root.current.sensitivity || 0)
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        onPressedChanged: {
                            if (!pressed)
                                root.bridge.perform("input.set", { key: "sensitivity", value: Number(value.toFixed(2)) })
                        }
                    }
                    Text {
                        text: Number(root.current.sensitivity || 0).toFixed(2)
                        color: root.muted
                        font.pixelSize: 11
                        Layout.preferredWidth: 38
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Touchpad"
                description: (root.state.touchpads || []).length > 0
                    ? "Common compositor-backed touchpad controls."
                    : "No touchpad is currently reported; preferences remain available for future sessions."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Natural scrolling"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        checked: !!root.current.naturalScroll
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "naturalScroll", value: checked })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Tap to click"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        checked: !!root.current.tapToClick
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "tapToClick", value: checked })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Disable while typing"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        checked: !!root.current.disableWhileTyping
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "disableWhileTyping", value: checked })
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
