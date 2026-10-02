import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.input ? bridge.state.input : ({})
    readonly property var current: state.current || ({})
    property int selectedTouchpadIndex: 0
    readonly property string selectedTouchpad: {
        const rows = state.touchpads || []
        return selectedTouchpadIndex >= 0 && selectedTouchpadIndex < rows.length
            ? String(rows[selectedTouchpadIndex]) : ""
    }
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    function touchpadSpeed() {
        const values = state.touchpadSpeeds || ({})
        return selectedTouchpad.length > 0 && values[selectedTouchpad] !== undefined
            ? Number(values[selectedTouchpad]) : 0
    }

    Connections {
        target: root.bridge
        function onStateChanged() {
            const rows = root.state.touchpads || []
            if (root.selectedTouchpadIndex >= rows.length)
                root.selectedTouchpadIndex = 0
        }
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar {
            foreground: root.foreground
        }

        ColumnLayout {
            width: Math.max(0, root.width - 14)
            spacing: 14

            PageHeader {
                title: "Input"
                subtitle: "Keyboard, pointer and touchpad preferences"
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
                description: "Truthful compositor inventory. Device-specific touchpad speed is keyed to the exact Hyprland device identity."
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
                description: "Hyprland-backed pointer speed, acceleration profile, scrolling direction, and primary-button preference."
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

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Acceleration · " + (root.current.accelProfile === "default" ? "compositor default" : root.current.accelProfile)
                        color: root.foreground
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    ChoicePill {
                        text: "Adaptive"
                        selected: root.current.accelProfile === "adaptive"
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "accelProfile", value: "adaptive" })
                    }
                    ChoicePill {
                        text: "Flat"
                        selected: root.current.accelProfile === "flat"
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "accelProfile", value: "flat" })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Natural scrolling"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        checked: !!root.current.mouseNaturalScroll
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "mouseNaturalScroll", value: checked })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Primary button on right"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        checked: !!root.current.leftHanded
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("input.set", { key: "leftHanded", value: checked })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Touchpad"
                description: (root.state.touchpads || []).length > 0
                    ? "Global touchpad behavior plus per-device pointer speed through Hyprland's Lua device authority."
                    : "No touchpad is currently reported; global touchpad preferences remain available for future sessions."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    visible: (root.state.touchpads || []).length > 1
                    Layout.fillWidth: true
                    model: root.state.touchpads || []
                    currentIndex: root.selectedTouchpadIndex
                    enabled: !root.bridge.actionBusy
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    onActivated: root.selectedTouchpadIndex = index
                }

                RowLayout {
                    visible: root.selectedTouchpad.length > 0
                        && !!(root.state.capabilities || {}).touchpadSpeed
                    Layout.fillWidth: true
                    Text { text: "Pointer speed"; color: root.foreground; font.pixelSize: 13 }
                    MahoSlider {
                        Layout.fillWidth: true
                        from: -1
                        to: 1
                        stepSize: 0.05
                        value: root.touchpadSpeed()
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        onPressedChanged: {
                            if (!pressed && root.selectedTouchpad.length > 0)
                                root.bridge.perform("input.set", {
                                    key: "touchpadSensitivity",
                                    device: root.selectedTouchpad,
                                    value: Number(value.toFixed(2))
                                })
                        }
                    }
                    Text {
                        text: root.touchpadSpeed().toFixed(2)
                        color: root.muted
                        font.pixelSize: 11
                        Layout.preferredWidth: 38
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Natural scrolling"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        checked: !!root.current.naturalScroll
                        enabled: !root.bridge.actionBusy
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
                        enabled: !root.bridge.actionBusy
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
                        enabled: !root.bridge.actionBusy
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
