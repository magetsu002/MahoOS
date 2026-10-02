import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.diagnostics ? bridge.state.diagnostics : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar { foreground: root.foreground; reducedMotion: root.bridge && root.bridge.state.appearance ? !!root.bridge.state.appearance.reducedMotion : false }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 14

            PageHeader {
                title: "Diagnostics"
                subtitle: "Configuration health and Settings providers"
                foreground: root.foreground
                muted: root.muted
            }

            SettingCard {
                title: root.state.configurationHealthy ? "Configuration healthy" : "Configuration issue detected"
                description: root.state.configurationHealthy
                    ? "Hyprland reports no active configuration errors."
                    : ((root.state.configErrors || []).join("\n") || root.state.providerError || "Configuration health could not be confirmed.")
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted
            }

            SettingCard {
                title: "Settings providers"
                description: "Availability only. This page does not claim system health or Guardian trust."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.providers || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.name
                        trailingText: modelData.available ? "Available" : "Unavailable"
                        foreground: root.foreground
                        muted: root.muted
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
