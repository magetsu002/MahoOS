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

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

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
        contentWidth: availableWidth
        ScrollBar.vertical: MahoScrollBar {
            foreground: theme.textPrimary
            reducedMotion: theme.reducedMotion
        }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Input"
                subtitle: "Keyboard, mouse and touchpad preferences"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Input state unavailable"
                detail: root.state.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            MahoSectionLabel {
                visible: !!root.state.available
                text: "Keyboard"
                textColor: theme.textSecondary
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Repeat rate"
                description: "How quickly a held key repeats"
                iconName: "input-keyboard"
                theme: theme

                MahoTextField {
                    Layout.preferredWidth: 112
                    backendOwned: true
                    backendText: Number(root.current.repeatRate || 25).toString()
                    validator: IntValidator { bottom: 1; top: 100 }
                    surface: theme.surfaceElevated
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    enabled: !root.bridge.actionBusy
                    onTextRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "repeatRate",
                            value: Number(value)
                        })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Repeat delay"
                description: "Delay before a held key starts repeating"
                iconName: "input-keyboard"
                theme: theme

                MahoTextField {
                    Layout.preferredWidth: 112
                    backendOwned: true
                    backendText: Number(root.current.repeatDelay || 600).toString()
                    validator: IntValidator { bottom: 100; top: 2000 }
                    surface: theme.surfaceElevated
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    enabled: !root.bridge.actionBusy
                    onTextRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "repeatDelay",
                            value: Number(value)
                        })
                    }
                }

                Text {
                    text: "ms"
                    color: theme.textSecondary
                    font.pixelSize: 11
                }
            }

            MahoSectionLabel {
                visible: !!root.state.available
                text: "Mouse"
                textColor: theme.textSecondary
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Pointer speed"
                description: "Adjust mouse sensitivity"
                iconName: "input-mouse"
                theme: theme

                MahoSlider {
                    Layout.preferredWidth: Math.min(280, Math.max(170, root.width * 0.28))
                    from: -1
                    to: 1
                    stepSize: 0.05
                    backendOwned: true
                    backendValue: Number(root.current.sensitivity || 0)
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    onValueRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "sensitivity",
                            value: Number(value.toFixed(2))
                        })
                    }
                }

                Text {
                    text: Number(root.current.sensitivity || 0).toFixed(2)
                    color: theme.textSecondary
                    font.pixelSize: 11
                    Layout.preferredWidth: 38
                    horizontalAlignment: Text.AlignRight
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Acceleration"
                description: root.current.accelProfile === "default"
                    ? "Using the compositor default profile"
                    : "Choose how pointer acceleration behaves"
                iconName: "input-mouse"
                theme: theme

                ChoicePill {
                    text: "Adaptive"
                    selected: root.current.accelProfile === "adaptive"
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.bridge.perform("input.set", {
                        key: "accelProfile",
                        value: "adaptive"
                    })
                }

                ChoicePill {
                    text: "Flat"
                    selected: root.current.accelProfile === "flat"
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.bridge.perform("input.set", {
                        key: "accelProfile",
                        value: "flat"
                    })
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Natural scrolling"
                description: "Move content in the same direction as your fingers"
                iconName: "input-mouse"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.current.mouseNaturalScroll
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "mouseNaturalScroll",
                            value: value
                        })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Primary button"
                description: root.current.leftHanded ? "Right button is primary" : "Left button is primary"
                iconName: "input-mouse"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.current.leftHanded
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "leftHanded",
                            value: value
                        })
                    }
                }
            }

            MahoSectionLabel {
                visible: !!root.state.available
                text: "Touchpad"
                textColor: theme.textSecondary
            }

            AppearanceRow {
                visible: !!root.state.available && (root.state.touchpads || []).length > 1
                title: "Touchpad"
                description: "Choose which touchpad to configure"
                iconName: "input-touchpad"
                theme: theme

                MahoComboBox {
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.touchpads || []
                    currentIndex: root.selectedTouchpadIndex
                    enabled: !root.bridge.actionBusy
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: root.selectedTouchpadIndex = index
                }
            }

            AppearanceRow {
                visible: !!root.state.available && root.selectedTouchpad.length > 0
                    && !!(root.state.capabilities || {}).touchpadSpeed
                title: "Touchpad speed"
                description: root.selectedTouchpad
                iconName: "input-touchpad"
                theme: theme

                MahoSlider {
                    Layout.preferredWidth: Math.min(280, Math.max(170, root.width * 0.28))
                    from: -1
                    to: 1
                    stepSize: 0.05
                    backendOwned: true
                    backendValue: root.touchpadSpeed()
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    onValueRequested: function(value) {
                        if (root.selectedTouchpad.length > 0)
                            root.bridge.perform("input.set", {
                                key: "touchpadSensitivity",
                                device: root.selectedTouchpad,
                                value: Number(value.toFixed(2))
                            })
                    }
                }

                Text {
                    text: root.touchpadSpeed().toFixed(2)
                    color: theme.textSecondary
                    font.pixelSize: 11
                    Layout.preferredWidth: 38
                    horizontalAlignment: Text.AlignRight
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Natural scrolling"
                description: "Move content in the same direction as your fingers"
                iconName: "input-touchpad"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.current.naturalScroll
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "naturalScroll",
                            value: value
                        })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Tap to click"
                description: "Tap the touchpad to click"
                iconName: "input-touchpad"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.current.tapToClick
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "tapToClick",
                            value: value
                        })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Disable while typing"
                description: "Ignore accidental touchpad input while typing"
                iconName: "input-touchpad"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.current.disableWhileTyping
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("input.set", {
                            key: "disableWhileTyping",
                            value: value
                        })
                    }
                }
            }

            Text {
                visible: !!root.state.available
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: "Detected: "
                    + String((root.state.keyboards || []).length) + " keyboard(s), "
                    + String((root.state.mice || []).length) + " mouse device(s), "
                    + String((root.state.touchpads || []).length) + " touchpad(s)."
                color: theme.textFaint
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
