import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.motion ? bridge.state.motion : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

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
        ScrollBar.vertical: MahoScrollBar { foreground: root.foreground }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 14

            PageHeader {
                title: "Motion"
                subtitle: "Current animation behavior from the live Maho desktop"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Motion state unavailable"
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
                title: "Configured animations"
                description: "Only Maho-overridden animation leaves are shown. Editing is read-only in this milestone."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.animations || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.name
                        description: root.animationDetail(modelData)
                        trailingText: modelData.curve || "default"
                        foreground: root.foreground
                        muted: root.muted
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available && (root.state.curves || []).length > 0
                title: "Bézier curves"
                description: "Live curve definitions currently loaded by Hyprland."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.curves || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        title: modelData.name
                        description: "Control points"
                        trailingText: root.curvePoints(modelData)
                        foreground: root.foreground
                        muted: root.muted
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
