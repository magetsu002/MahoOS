import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.region ? bridge.state.region : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function stringIndex(rows, value) {
        if (!rows)
            return -1
        return Math.max(-1, rows.indexOf(value))
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
                title: "Region & Time"
                subtitle: "Language, keyboard layout, time and timezone"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Region and time state unavailable"
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
                title: "Time zone"
                description: root.state.timeSynchronized
                    ? "Clock synchronization is active"
                    : "Clock synchronization is not currently confirmed"
                iconName: "preferences-system-time"
                theme: theme

                MahoComboBox {
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.timezones || []
                    currentIndex: root.stringIndex(model, root.state.timezone || "")
                    enabled: !!root.state.timezoneControlAvailable && !root.bridge.actionBusy
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: {
                        if (index >= 0)
                            root.bridge.perform("region.timezone", { timezone: model[index] })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Set time automatically"
                description: "Keep the system clock synchronized automatically"
                iconName: "appointment-soon"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.state.automaticTime
                    enabled: !!root.state.automaticTimeControlAvailable && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) { root.bridge.perform("region.automaticTime", { enabled: value }) }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Regional format"
                description: "Choose the system locale used for regional formatting"
                iconName: "preferences-desktop-locale"
                theme: theme

                MahoComboBox {
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.locales || []
                    currentIndex: root.stringIndex(model, root.state.locale || "")
                    enabled: !!root.state.localeControlAvailable && !root.bridge.actionBusy
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: {
                        if (index >= 0)
                            root.bridge.perform("region.locale", { locale: model[index] })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Keyboard layout"
                description: "Choose the active keyboard layout"
                iconName: "input-keyboard"
                theme: theme

                MahoComboBox {
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.keyboardLayouts || []
                    currentIndex: root.stringIndex(model, root.state.keyboardLayout || "")
                    enabled: !!root.state.keyboardLayoutControlAvailable && !root.bridge.actionBusy
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: {
                        if (index >= 0)
                            root.bridge.perform("region.keyboardLayout", { layout: model[index] })
                    }
                }
            }

            Text {
                visible: !!root.state.available
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: "Regional format remains delegated to systemd-localed."
                color: theme.textFaint
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
