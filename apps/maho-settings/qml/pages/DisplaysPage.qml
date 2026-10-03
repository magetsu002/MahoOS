import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.displays ? bridge.state.displays : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    property int selectedOutputIndex: 0
    property string pendingToken: ""
    property int rollbackRemaining: 0

    readonly property var output: {
        const rows = pageState.outputs || []
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
            const rows = root.pageState.outputs || []
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
        contentWidth: availableWidth
        ScrollBar.vertical: MahoScrollBar {
            foreground: theme.textPrimary
            reducedMotion: theme.reducedMotion
        }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Displays"
                subtitle: "Resolution, refresh rate, scale and arrangement"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Display backend unavailable"
                detail: root.pageState.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Output"
                description: root.output.description || "Select an active compositor output."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoComboBox {
                    id: outputBox
                    Layout.fillWidth: true
                    model: root.pageState.outputs || []
                    textRole: "name"
                    currentIndex: root.selectedOutputIndex
                    surface: theme.surfaceElevated
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: function(index) {
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
                    color: theme.textSecondary
                    font.pixelSize: 11
                    Layout.fillWidth: true
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Enabled"
                        color: theme.textPrimary
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    MahoSwitch {
                        reducedMotion: theme.reducedMotion
                        id: outputEnabled
                        checked: false
                        enabled: root.output.disabled || Number(root.pageState.enabledCount || 0) > 1
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onToggleRequested: function(value) { outputEnabled.checked = value }
                    }
                }

                Text {
                    visible: !!root.output.enabled && Number(root.pageState.enabledCount || 0) <= 1
                    text: "The last active display cannot be disabled."
                    color: theme.textSecondary
                    font.pixelSize: 10
                    Layout.fillWidth: true
                }
            }

            SettingCard {
                visible: !!root.pageState.available && !!root.output.name
                title: "Mode"
                description: "Resolution and refresh choices are constrained to modes advertised by the selected output."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                GridLayout {
                    enabled: outputEnabled.checked
                    opacity: enabled ? 1.0 : 0.45
                    columns: root.width < 760 ? 1 : 2
                    columnSpacing: 12
                    rowSpacing: 10
                    Layout.fillWidth: true

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Resolution"; color: theme.textSecondary; font.pixelSize: 11 }
                        MahoComboBox {
                            id: resolutionBox
                            Layout.fillWidth: true
                            surface: theme.surfaceElevated
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                            onActivated: function(index) {
                                const refreshes = root.refreshOptions(currentText)
                                refreshBox.model = refreshes
                                refreshBox.currentIndex = 0
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Refresh rate"; color: theme.textSecondary; font.pixelSize: 11 }
                        MahoComboBox {
                            id: refreshBox
                            Layout.fillWidth: true
                            surface: theme.surfaceElevated
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                            displayText: currentIndex >= 0 && model && model.length > currentIndex
                                ? Number(model[currentIndex]).toFixed(2) + " Hz"
                                : ""
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Scale"; color: theme.textSecondary; font.pixelSize: 11 }
                        MahoTextField {
                            id: scaleField
                            Layout.fillWidth: true
                            validator: DoubleValidator { bottom: 0.5; top: 4.0; decimals: 3 }
                            surface: theme.surfaceElevated
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Text { text: "Orientation"; color: theme.textSecondary; font.pixelSize: 11 }
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
                            surface: theme.surfaceElevated
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available && !!root.output.name
                title: "Arrangement"
                description: "Coordinates define output placement. Hyprland does not expose a truthful global “primary display” concept, so Settings does not invent one."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "X"; color: theme.textSecondary; font.pixelSize: 11 }
                    MahoTextField {
                        id: xField
                        Layout.fillWidth: true
                        validator: IntValidator { bottom: -32768; top: 32768 }
                        surface: theme.surfaceElevated
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        accent: theme.accent
                    }
                    Text { text: "Y"; color: theme.textSecondary; font.pixelSize: 11 }
                    MahoTextField {
                        id: yField
                        Layout.fillWidth: true
                        validator: IntValidator { bottom: -32768; top: 32768 }
                        surface: theme.surfaceElevated
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        accent: theme.accent
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    MahoIconButton {
                        iconName: "focus"
                        label: root.output.focused ? "Focused display" : "Focus display"
                        emphasized: !!root.output.focused
                        enabled: !!root.output.enabled && !root.output.focused
                            && !root.bridge.actionBusy && root.pendingToken.length === 0
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.bridge.perform("display.focus", { name: root.output.name })
                    }
                    Item { Layout.fillWidth: true }
                    MahoIconButton {
                        iconName: "preview"
                        label: "Preview display changes"
                        emphasized: true
                        enabled: !root.bridge.actionBusy && root.pendingToken.length === 0
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.preview()
                    }
                }
            }

            SettingCard {
                visible: root.pendingToken.length > 0
                title: "Keep this display configuration?"
                description: "If you do nothing, the independent watchdog restores the previous outputs automatically."
                surface: theme.surfaceElevated
                borderColor: Qt.rgba(theme.accent.r, theme.accent.g, theme.accent.b, 0.42)
                foreground: theme.textPrimary
                muted: theme.textSecondary

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Reverting in " + root.rollbackRemaining + "s"
                        color: theme.textSecondary
                        font.pixelSize: 12
                        Layout.fillWidth: true
                    }
                    ChoicePill {
                        text: "Revert"
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        surface: theme.surfaceElevated
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.bridge.perform("display.revert", { token: root.pendingToken })
                    }
                    ChoicePill {
                        text: "Keep"
                        selected: true
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        surface: theme.surfaceElevated
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.bridge.perform("display.commit", { token: root.pendingToken })
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }

    Component.onCompleted: Qt.callLater(root.syncControls)
}
