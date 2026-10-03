import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.sound ? bridge.state.sound : ({})

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
                visible: !root.pageState.available && !root.bridge.loading
                title: "Audio backend unavailable"
                detail: root.pageState.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Output device"
                description: "Choose where MahoOS plays audio"
                iconName: "audio-volume-high"
                theme: theme

                MahoComboBox {
                    id: outputSelector
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.pageState.outputs || []
                    textRole: "name"
                    backendOwned: true
                    busy: root.bridge.actionBusy
                    backendIndex: root.defaultIndex(root.pageState.outputs)
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    enabled: count > 0
                    onIndexRequested: function(index) {
                        const row = root.pageState.outputs[index]
                        if (row)
                            root.bridge.perform("sound.default", { direction: "output", id: row.id })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Output volume"
                description: root.pageState.output && !root.pageState.output.available
                    ? (root.pageState.output.error || "Current output state is unavailable")
                    : "Adjust the current output level"
                iconName: "audio-volume-high"
                theme: theme

                MahoSlider {
                    Layout.preferredWidth: Math.min(260, Math.max(150, root.width * 0.26))
                    from: 0
                    to: 100
                    backendOwned: true
                    busy: root.bridge.actionBusy
                    backendValue: root.pageState.output && root.pageState.output.available ? root.pageState.output.volume : 0
                    enabled: !!(root.pageState.output && root.pageState.output.available)
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
                    text: (root.pageState.output ? root.pageState.output.volume : 0) + "%"
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
                    busy: root.bridge.actionBusy
                    reducedMotion: theme.reducedMotion
                    checked: root.pageState.output && root.pageState.output.available
                        ? !!root.pageState.output.muted : false
                    enabled: !!(root.pageState.output && root.pageState.output.available)
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
                visible: !!root.pageState.available
                title: "Input device"
                description: "Choose the microphone MahoOS uses"
                iconName: "audio-input-microphone"
                theme: theme

                MahoComboBox {
                    id: inputSelector
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.pageState.inputs || []
                    textRole: "name"
                    backendOwned: true
                    busy: root.bridge.actionBusy
                    backendIndex: root.defaultIndex(root.pageState.inputs)
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    enabled: count > 0
                    onIndexRequested: function(index) {
                        const row = root.pageState.inputs[index]
                        if (row)
                            root.bridge.perform("sound.default", { direction: "input", id: row.id })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Input level"
                description: root.pageState.input && !root.pageState.input.available
                    ? (root.pageState.input.error || "Current input state is unavailable")
                    : "Adjust microphone gain"
                iconName: "audio-input-microphone"
                theme: theme

                MahoSlider {
                    Layout.preferredWidth: Math.min(260, Math.max(150, root.width * 0.26))
                    from: 0
                    to: 100
                    backendOwned: true
                    busy: root.bridge.actionBusy
                    backendValue: root.pageState.input && root.pageState.input.available ? root.pageState.input.volume : 0
                    enabled: !!(root.pageState.input && root.pageState.input.available)
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
                    text: (root.pageState.input ? root.pageState.input.volume : 0) + "%"
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
                    busy: root.bridge.actionBusy
                    reducedMotion: theme.reducedMotion
                    checked: root.pageState.input && root.pageState.input.available
                        ? !!root.pageState.input.muted : false
                    enabled: !!(root.pageState.input && root.pageState.input.available)
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
