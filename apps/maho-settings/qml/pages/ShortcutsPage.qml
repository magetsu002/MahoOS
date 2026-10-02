pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var pageState: bridge && bridge.state.shortcuts ? bridge.state.shortcuts : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function filteredBinds() {
        const rows = root.pageState.binds || []
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
        ScrollBar.vertical: MahoScrollBar { foreground: theme.textPrimary; reducedMotion: theme.reducedMotion }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Shortcuts"
                subtitle: "Inspect the shortcuts active in this Maho session"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Shortcut state unavailable"
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
                title: "Active shortcuts"
                description: "Read directly from Hyprland. Editing remains disabled until the Maho configuration writer is certified."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoTextField {
                    id: filterField
                    Layout.fillWidth: true
                    placeholderText: "Filter shortcuts..."
                    surface: theme.surfaceElevated
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                Repeater {
                    model: root.filteredBinds()
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.chord || "Unknown shortcut"
                        description: modelData.description || "Managed action"
                        trailingText: modelData.submap ? "Submap: " + modelData.submap : (modelData.repeat ? "Repeats" : "")
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
