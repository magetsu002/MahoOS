import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.sound ? bridge.state.sound : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function defaultIndex(rows) {
        if (!rows)
            return -1
        for (let i = 0; i < rows.length; ++i)
            if (rows[i].default)
                return i
        return rows.length > 0 ? 0 : -1
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
                title: "Sound"
                subtitle: "Choose audio devices and adjust their levels"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Audio backend unavailable"
                detail: root.state.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Output device"
                description: "Choose where MahoOS plays audio"
                iconName: "audio-volume-high"
                theme: theme

                MahoComboBox {
                    id: outputSelector
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.outputs || []
                    textRole: "name"
                    backendOwned: true
                    backendIndex: root.defaultIndex(root.state.outputs)
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    enabled: count > 0 && !root.bridge.actionBusy
                    onIndexRequested: function(index) {
                        const row = root.state.outputs[index]
                        if (row)
                            root.bridge.perform("sound.default", { direction: "output", id: row.id })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Output volume"
                description: root.state.output && !root.state.output.available
                    ? (root.state.output.error || "Current output state is unavailable")
                    : "Adjust the current output level"
                iconName: "audio-volume-high"
                theme: theme

                MahoSlider {
                    Layout.preferredWidth: Math.min(260, Math.max(150, root.width * 0.26))
                    from: 0
                    to: 100
                    backendOwned: true
                    backendValue: root.state.output && root.state.output.available ? root.state.output.volume : 0
                    enabled: !!(root.state.output && root.state.output.available) && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    onValueRequested: function(value) {
                        root.bridge.perform("sound.volume", {
                            direction: "output",
                            percent: Math.round(value)
                        })
                    }
                }

                Text {
                    text: (root.state.output ? root.state.output.volume : 0) + "%"
                    color: theme.textSecondary
                    font.pixelSize: 11
                    Layout.preferredWidth: 38
                    horizontalAlignment: Text.AlignRight
                }

                Text {
                    text: "Mute"
                    color: theme.textSecondary
                    font.pixelSize: 11
                }

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: root.state.output && root.state.output.available
                        ? !!root.state.output.muted : false
                    enabled: !!(root.state.output && root.state.output.available) && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("sound.mute", {
                            direction: "output",
                            muted: value
                        })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Input device"
                description: "Choose the microphone MahoOS uses"
                iconName: "audio-input-microphone"
                theme: theme

                MahoComboBox {
                    id: inputSelector
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.inputs || []
                    textRole: "name"
                    backendOwned: true
                    backendIndex: root.defaultIndex(root.state.inputs)
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    enabled: count > 0 && !root.bridge.actionBusy
                    onIndexRequested: function(index) {
                        const row = root.state.inputs[index]
                        if (row)
                            root.bridge.perform("sound.default", { direction: "input", id: row.id })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Input level"
                description: root.state.input && !root.state.input.available
                    ? (root.state.input.error || "Current input state is unavailable")
                    : "Adjust microphone gain"
                iconName: "audio-input-microphone"
                theme: theme

                MahoSlider {
                    Layout.preferredWidth: Math.min(260, Math.max(150, root.width * 0.26))
                    from: 0
                    to: 100
                    backendOwned: true
                    backendValue: root.state.input && root.state.input.available ? root.state.input.volume : 0
                    enabled: !!(root.state.input && root.state.input.available) && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    onValueRequested: function(value) {
                        root.bridge.perform("sound.volume", {
                            direction: "input",
                            percent: Math.round(value)
                        })
                    }
                }

                Text {
                    text: (root.state.input ? root.state.input.volume : 0) + "%"
                    color: theme.textSecondary
                    font.pixelSize: 11
                    Layout.preferredWidth: 38
                    horizontalAlignment: Text.AlignRight
                }

                Text {
                    text: "Mute"
                    color: theme.textSecondary
                    font.pixelSize: 11
                }

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: root.state.input && root.state.input.available
                        ? !!root.state.input.muted : false
                    enabled: !!(root.state.input && root.state.input.available) && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) {
                        root.bridge.perform("sound.mute", {
                            direction: "input",
                            muted: value
                        })
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
