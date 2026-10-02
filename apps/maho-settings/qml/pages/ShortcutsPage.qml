import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.shortcuts ? bridge.state.shortcuts : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    function filteredBinds() {
        const rows = root.state.binds || []
        const q = filterField.text.trim().toLowerCase()
        if (q.length === 0)
            return rows
        return rows.filter(function(row) {
            return String(row.chord || "").toLowerCase().includes(q)
                || String(row.description || "").toLowerCase().includes(q)
                || String(row.submap || "").toLowerCase().includes(q)
        })
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar { foreground: root.foreground }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 14

            PageHeader {
                title: "Shortcuts"
                subtitle: "Inspect the shortcuts active in this Maho session"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Shortcut state unavailable"
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
                title: "Active shortcuts"
                description: "Read directly from Hyprland. Editing remains disabled until the Maho configuration writer is certified."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoTextField {
                    id: filterField
                    Layout.fillWidth: true
                    placeholderText: "Filter shortcuts..."
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                }

                Repeater {
                    model: root.filteredBinds()
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.chord || "Unknown shortcut"
                        description: modelData.description || "Managed action"
                        trailingText: modelData.submap ? "Submap: " + modelData.submap : (modelData.repeat ? "Repeats" : "")
                        foreground: root.foreground
                        muted: root.muted
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
