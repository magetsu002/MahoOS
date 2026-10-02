import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.displays ? bridge.state.displays : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"
    property int selectedOutputIndex: 0
    property string pendingToken: ""
    property int rollbackRemaining: 0

    readonly property var output: {
        const rows = state.outputs || []
        return selectedOutputIndex >= 0 && selectedOutputIndex < rows.length ? rows[selectedOutputIndex] : ({})
    }

    function resolutionOptions() {
        const result = []
        const modes = output.modes || []
        for (let i = 0; i < modes.length; ++i) {
            const value = modes[i].resolution
            if (result.indexOf(value) < 0)
                result.push(value)
        }
        if (output.enabled && output.resolution && result.indexOf(output.resolution) < 0)
            result.unshift(output.resolution)
        return result
    }

    function refreshOptions(resolution) {
        const result = []
        const modes = output.modes || []
        for (let i = 0; i < modes.length; ++i) {
            if (modes[i].resolution !== resolution)
                continue
            const value = Number(modes[i].refresh)
            if (!result.some(function(item) { return Math.abs(item - value) < 0.01 }))
                result.push(value)
        }
        result.sort(function(a, b) { return b - a })
        if (result.length === 0 && output.refresh)
            result.push(Number(output.refresh))
        return result
    }

    function syncControls() {
        const out = root.output
        if (!out || !out.name)
            return
        const resolutions = root.resolutionOptions()
        resolutionBox.model = resolutions
        resolutionBox.currentIndex = Math.max(0, resolutions.indexOf(out.resolution))
        const refreshes = root.refreshOptions(resolutionBox.currentText)
        refreshBox.model = refreshes
        let best = 0
        for (let i = 0; i < refreshes.length; ++i)
            if (Math.abs(refreshes[i] - Number(out.refresh)) < Math.abs(refreshes[best] - Number(out.refresh)))
                best = i
        refreshBox.currentIndex = best
        scaleField.text = Number(out.scale || 1).toString()
        xField.text = Number(out.x || 0).toString()
        yField.text = Number(out.y || 0).toString()
        orientationBox.currentIndex = Math.max(0, Number(out.transform || 0))
        outputEnabled.checked = !!out.enabled
    }

    function preview() {
        if (!output.name || resolutionBox.currentText.length === 0 || refreshBox.currentIndex < 0)
            return
        bridge.perform("display.preview", {
            name: output.name,
            resolution: resolutionBox.currentText,
            refresh: Number(refreshBox.model[refreshBox.currentIndex]),
            scale: Number(scaleField.text),
            x: Number(xField.text),
            y: Number(yField.text),
            transform: orientationBox.currentValue,
            enabled: outputEnabled.checked
        })
    }

    Connections {
        target: root.bridge
        ignoreUnknownSignals: true
        function onStateChanged() {
            const rows = root.state.outputs || []
            if (root.selectedOutputIndex >= rows.length)
                root.selectedOutputIndex = 0
            Qt.callLater(root.syncControls)
        }
        function onActionFinished(action, ok, message, result) {
            if (action === "display.preview" && ok) {
                root.pendingToken = result.token || ""
                root.rollbackRemaining = Number(result.rollbackSeconds || 15)
                rollbackTimer.restart()
            } else if ((action === "display.commit" || action === "display.revert") && ok) {
                root.pendingToken = ""
                rollbackTimer.stop()
            }
        }
    }

    Timer {
        id: rollbackTimer
        interval: 1000
        repeat: true
        onTriggered: {
            root.rollbackRemaining -= 1
            if (root.rollbackRemaining <= 0) {
                stop()
                root.pendingToken = ""
                root.bridge.refresh()
            }
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
                title: "Displays"
                subtitle: "Configure resolution, refresh rate, scale and layout"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Display backend unavailable"
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
                description: root.output.description || "Select an active compositor output."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    id: outputBox
                    Layout.fillWidth: true
                    model: root.state.outputs || []
                    textRole: "name"
                    currentIndex: root.selectedOutputIndex
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    onActivated: {
                        root.selectedOutputIndex = index
                        Qt.callLater(root.syncControls)
                    }
                }

                Text {
                    text: root.output.name
                        ? (root.output.enabled
                            ? root.output.resolution + " @ " + Number(root.output.refresh).toFixed(2) + " Hz · scale " + root.output.scale
                            : "Disabled")
                            + (root.output.focused ? " · focused" : "")
                        : ""
                    color: root.muted
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Enabled"
                        color: root.foreground
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    MahoSwitch {
                        reducedMotion: root.bridge && root.bridge.state.appearance ? !!root.bridge.state.appearance.reducedMotion : false
                        id: outputEnabled
                        checked: !!root.output.enabled
                        enabled: !root.bridge.actionBusy
                            && (root.output.disabled || Number(root.state.enabledCount || 0) > 1)
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                    }
                }

                Text {
                    visible: !!root.output.enabled && Number(root.state.enabledCount || 0) <= 1
                    text: "The last active display cannot be disabled."
                    color: root.muted
                    font.pixelSize: 10
                    Layout.fillWidth: true
                }
            }

            SettingCard {
                visible: !!root.state.available && !!root.output.name
                title: "Mode"
                description: "Resolution and refresh choices are constrained to modes advertised by the selected output."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                GridLayout {
                    enabled: outputEnabled.checked
                    opacity: enabled ? 1.0 : 0.45
                    columns: root.width < 760 ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 10
                    Layout.fillWidth: true

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Resolution"; color: root.muted; font.pixelSize: 11 }
                        MahoComboBox {
                            id: resolutionBox
                            Layout.fillWidth: true
                            surface: root.surface
                            foreground: root.foreground
                            muted: root.muted
                            accent: root.accent
                            onActivated: {
                                const refreshes = root.refreshOptions(currentText)
                                refreshBox.model = refreshes
                                refreshBox.currentIndex = 0
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Refresh rate"; color: root.muted; font.pixelSize: 11 }
                        MahoComboBox {
                            id: refreshBox
                            Layout.fillWidth: true
                            surface: root.surface
                            foreground: root.foreground
                            muted: root.muted
                            accent: root.accent
                            displayText: currentIndex >= 0 && model && model.length > currentIndex
                                ? Number(model[currentIndex]).toFixed(2) + " Hz"
                                : ""
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Scale"; color: root.muted; font.pixelSize: 11 }
                        TextField {
                            id: scaleField
                            Layout.fillWidth: true
                            validator: DoubleValidator { bottom: 0.5; top: 4.0; decimals: 3 }
                            color: root.foreground
                            background: Rectangle {
                                radius: 11
                                color: root.surface
                                border.width: 1
                                border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Orientation"; color: root.muted; font.pixelSize: 11 }
                        MahoComboBox {
                            id: orientationBox
                            Layout.fillWidth: true
                            model: [
                                { label: "Landscape", value: 0 },
                                { label: "Portrait (90°)", value: 1 },
                                { label: "Landscape (180°)", value: 2 },
                                { label: "Portrait (270°)", value: 3 }
                            ]
                            textRole: "label"
                            valueRole: "value"
                            surface: root.surface
                            foreground: root.foreground
                            muted: root.muted
                            accent: root.accent
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available && !!root.output.name
                title: "Arrangement"
                description: "Coordinates define output placement. Hyprland does not expose a truthful global “primary display” concept, so Settings does not invent one."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "X"; color: root.muted; font.pixelSize: 11 }
                    TextField {
                        id: xField
                        Layout.fillWidth: true
                        validator: IntValidator { bottom: -32768; top: 32768 }
                        color: root.foreground
                        background: Rectangle {
                            radius: 11
                            color: root.surface
                            border.width: 1
                            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
                        }
                    }
                    Text { text: "Y"; color: root.muted; font.pixelSize: 11 }
                    TextField {
                        id: yField
                        Layout.fillWidth: true
                        validator: IntValidator { bottom: -32768; top: 32768 }
                        color: root.foreground
                        background: Rectangle {
                            radius: 11
                            color: root.surface
                            border.width: 1
                            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    ChoicePill {
                        text: root.output.focused ? "Focused" : "Focus Display"
                        selected: !!root.output.focused
                        enabled: !!root.output.enabled && !root.output.focused
                            && !root.bridge.actionBusy && root.pendingToken.length === 0
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("display.focus", { name: root.output.name })
                    }
                    Item { Layout.fillWidth: true }
                    ChoicePill {
                        text: "Preview Changes"
                        enabled: !root.bridge.actionBusy && root.pendingToken.length === 0
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.preview()
                    }
                }
            }

            SettingCard {
                visible: root.pendingToken.length > 0
                title: "Keep this display configuration?"
                description: "If you do nothing, the independent watchdog restores the previous outputs automatically."
                surface: root.surface
                borderColor: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.42)
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Reverting in " + root.rollbackRemaining + "s"
                        color: root.muted
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    ChoicePill {
                        text: "Revert"
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("display.revert", { token: root.pendingToken })
                    }
                    ChoicePill {
                        text: "Keep"
                        selected: true
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("display.commit", { token: root.pendingToken })
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }

    Component.onCompleted: Qt.callLater(root.syncControls)
}
