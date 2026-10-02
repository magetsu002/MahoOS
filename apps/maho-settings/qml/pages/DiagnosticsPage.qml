import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.diagnostics ? bridge.state.diagnostics : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar { foreground: theme.textPrimary; reducedMotion: theme.reducedMotion }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Diagnostics"
                subtitle: "Configuration health and Settings providers"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            SettingCard {
                title: root.state.configurationHealthy ? "Configuration healthy" : "Configuration issue detected"
                description: root.state.configurationHealthy
                    ? "Hyprland reports no active configuration errors."
                    : ((root.state.configErrors || []).join("\n") || root.state.providerError || "Configuration health could not be confirmed.")
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            SettingCard {
                title: "Settings providers"
                description: "Availability only. This page does not claim system health or Guardian trust."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.state.providers || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.name
                        trailingText: modelData.available ? "Available" : "Unavailable"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
