import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var palette
    readonly property var state: bridge && bridge.state.sound ? bridge.state.sound : ({})
    readonly property color foreground: palette ? palette.foreground : "#f3eef8"
    readonly property color muted: palette ? palette.muted : "#aaa3af"
    readonly property color accent: palette ? palette.accent : "#d0bcff"
    readonly property color surface: palette ? palette.surfaceElevated : "#2b2930"
    readonly property color borderColor: palette ? palette.border : "#3d3942"

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

        ColumnLayout {
            width: Math.max(0, root.width - 14)
            spacing: 14

            PageHeader {
                title: "Sound"
                subtitle: "PipeWire and WirePlumber remain authoritative. Settings only reads state and issues bounded wpctl requests."
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Audio backend unavailable"
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
                title: "Output"
                description: "Choose the default sink and adjust its current volume."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    Layout.fillWidth: true
                    model: root.state.outputs || []
                    textRole: "name"
                    currentIndex: root.defaultIndex(root.state.outputs)
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    enabled: count > 0 && !root.bridge.actionBusy
                    onActivated: {
                        const row = root.state.outputs[index]
                        if (row)
                            root.bridge.perform("sound.default", { direction: "output", id: row.id })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Volume"
                        color: root.foreground
                        font.pixelSize: 12
                    }
                    MahoSlider {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: root.state.output ? root.state.output.volume : 0
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        onPressedChanged: {
                            if (!pressed)
                                root.bridge.perform("sound.volume", { direction: "output", percent: Math.round(value) })
                        }
                    }
                    Text {
                        text: (root.state.output ? root.state.output.volume : 0) + "%"
                        color: root.muted
                        font.pixelSize: 11
                        Layout.preferredWidth: 38
                    }
                    MahoSwitch {
                        checked: root.state.output ? !!root.state.output.muted : false
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("sound.mute", { direction: "output", muted: checked })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Input"
                description: "Choose the default source and adjust microphone gain."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    Layout.fillWidth: true
                    model: root.state.inputs || []
                    textRole: "name"
                    currentIndex: root.defaultIndex(root.state.inputs)
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    enabled: count > 0 && !root.bridge.actionBusy
                    onActivated: {
                        const row = root.state.inputs[index]
                        if (row)
                            root.bridge.perform("sound.default", { direction: "input", id: row.id })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Input level"; color: root.foreground; font.pixelSize: 12 }
                    MahoSlider {
                        Layout.fillWidth: true
                        from: 0
                        to: 100
                        value: root.state.input ? root.state.input.volume : 0
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        onPressedChanged: {
                            if (!pressed)
                                root.bridge.perform("sound.volume", { direction: "input", percent: Math.round(value) })
                        }
                    }
                    Text {
                        text: (root.state.input ? root.state.input.volume : 0) + "%"
                        color: root.muted
                        font.pixelSize: 11
                        Layout.preferredWidth: 38
                    }
                    MahoSwitch {
                        checked: root.state.input ? !!root.state.input.muted : false
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("sound.mute", { direction: "input", muted: checked })
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
