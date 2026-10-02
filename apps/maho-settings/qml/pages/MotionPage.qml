import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var pageState: bridge && bridge.state.motion ? bridge.state.motion : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function animationDetail(row) {
        let detail = row.enabled ? "Enabled" : "Disabled"
        if (Number(row.speed || 0) > 0)
            detail += " · speed " + Number(row.speed).toFixed(1).replace(/\\.0$/, "")
        if (row.style)
            detail += " · " + row.style
        return detail
    }

    function curvePoints(row) {
        return "(" + row.x0.toFixed(2) + ", " + row.y0.toFixed(2) + ")  (" + row.x1.toFixed(2) + ", " + row.y1.toFixed(2) + ")"
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar { foreground: theme.textPrimary; reducedMotion: theme.reducedMotion }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Motion"
                subtitle: "Current animation behavior from the live Maho desktop"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Motion state unavailable"
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
                title: "Configured animations"
                description: "Only Maho-overridden animation leaves are shown. Editing is read-only in this milestone."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.animations || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.name
                        description: root.animationDetail(modelData)
                        trailingText: modelData.curve || "default"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available && (root.pageState.curves || []).length > 0
                title: "Bézier curves"
                description: "Live curve definitions currently loaded by Hyprland."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.curves || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.name
                        description: "Control points"
                        trailingText: root.curvePoints(modelData)
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
