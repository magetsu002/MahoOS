import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.configuration ? bridge.state.configuration : ({})

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
                title: "Configuration"
                subtitle: "Managed desktop configuration and current health"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Configuration state unavailable"
                detail: root.state.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            SettingCard {
                visible: !!root.state.available
                title: root.state.healthy ? "Configuration healthy" : "Configuration needs attention"
                description: root.state.healthy
                    ? "Hyprland reports no current configuration errors."
                    : "Hyprland reported configuration errors below."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.state.configErrors || []
                    delegate: MahoInsetRow {
                        required property string modelData
                        title: modelData
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Managed sources"
                description: "These files currently participate in the Maho desktop configuration."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.state.managedFiles || []
                    delegate: MahoInsetRow {
                        required property string modelData
                        title: modelData.split("/").pop()
                        description: modelData
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available && !root.state.mutationAvailable
                title: "Editing intentionally unavailable"
                description: "Maho does not yet have a certified single-owner writer for advanced Hyprland configuration. Read-only inspection is available without weakening ownership."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
