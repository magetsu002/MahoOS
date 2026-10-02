import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.configuration ? bridge.state.configuration : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar { foreground: root.foreground }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 14

            PageHeader {
                title: "Configuration"
                subtitle: "Managed desktop configuration and current health"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Configuration state unavailable"
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
                title: root.state.healthy ? "Configuration healthy" : "Configuration needs attention"
                description: root.state.healthy
                    ? "Hyprland reports no current configuration errors."
                    : "Hyprland reported configuration errors below."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.configErrors || []
                    delegate: MahoInsetRow {
                        required property string modelData
                        title: modelData
                        foreground: root.foreground
                        muted: root.muted
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Managed sources"
                description: "These files currently participate in the Maho desktop configuration."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.managedFiles || []
                    delegate: MahoInsetRow {
                        required property string modelData
                        title: modelData.split("/").pop()
                        description: modelData
                        foreground: root.foreground
                        muted: root.muted
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available && !root.state.mutationAvailable
                title: "Editing intentionally unavailable"
                description: "Maho does not yet have a certified single-owner writer for advanced Hyprland configuration. Read-only inspection is available without weakening ownership."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
