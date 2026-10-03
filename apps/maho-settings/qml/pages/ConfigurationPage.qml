pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.configuration ? bridge.state.configuration : ({})
    readonly property var writer: pageState.writer || ({})
    property bool confirmReset: false

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function managedCount() {
        const model = root.writer.model || {}
        const keys = ["binds", "windowRules", "workspaceRules", "layerRules", "curves", "animations", "startup"]
        let total = 0
        for (let i = 0; i < keys.length; ++i)
            total += (model[keys[i]] || []).length
        return total
    }

    Connections {
        target: root.bridge
        function onActionFinished(action, ok) {
            if (action === "configuration.reset" && ok)
                root.confirmReset = false
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
                title: "Configuration"
                subtitle: "Managed desktop configuration and current health"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Configuration state unavailable"
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
                title: root.pageState.healthy ? "Configuration healthy" : "Configuration needs attention"
                description: root.pageState.healthy
                    ? "Hyprland reports no current configuration errors."
                    : "Hyprland reported configuration errors below."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.configErrors || []
                    delegate: MahoInsetRow {
                        required property string modelData
                        required property int index
                        title: modelData
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.configErrors || []).length - 1
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Maho configuration writer"
                description: root.writer.loaderInstalled
                    ? "The mutable user overlay is loaded after immutable Maho defaults."
                    : "The user-overlay loader is not present in this runtime yet."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoInsetRow {
                    title: "Mutation authority"
                    trailingText: root.pageState.mutationAvailable ? "Ready" : "Read-only"
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                }

                MahoInsetRow {
                    title: "Managed overrides"
                    trailingText: String(root.managedCount())
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                }

                MahoInsetRow {
                    title: "Automatic backups"
                    trailingText: String(root.writer.backupCount || 0)
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                }

                MahoInsetRow {
                    title: "User overlay"
                    description: String(root.writer.overlayPath || "")
                    trailingText: root.writer.overlayExists ? "Present" : "Empty"
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    dividerVisible: false
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Managed sources"
                description: "Immutable Maho source files stay separate from the Settings-owned user overlay."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.managedFiles || []
                    delegate: MahoInsetRow {
                        required property string modelData
                        required property int index
                        title: modelData.split("/").pop()
                        description: modelData
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.managedFiles || []).length - 1
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available && !root.pageState.mutationAvailable
                title: "Editing unavailable"
                description: root.pageState.error
                    || "The certified writer is present in source, but this live runtime does not yet load the Maho Settings user overlay."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            SettingCard {
                visible: !!root.pageState.mutationAvailable && root.managedCount() > 0
                title: root.confirmReset ? "Confirm reset" : "Reset managed overrides"
                description: root.confirmReset
                    ? "This removes only Settings-owned Hyprland overrides. Immutable Maho defaults are not modified."
                    : "Return Shortcuts, Rules, Motion and Session overrides to the underlying configuration."
                surface: theme.surfaceElevated
                borderColor: root.confirmReset ? theme.controlActiveRim : theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }

                    ChoicePill {
                        visible: root.confirmReset
                        text: "Cancel"
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.confirmReset = false
                    }

                    ChoicePill {
                        text: root.confirmReset ? "Reset" : "Reset managed changes"
                        selected: root.confirmReset
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: {
                            if (!root.confirmReset) {
                                root.confirmReset = true
                            } else {
                                root.bridge.perform("configuration.reset", {})
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
