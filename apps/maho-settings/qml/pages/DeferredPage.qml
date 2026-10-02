import QtQuick
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    property string targetRoute: ""
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    function pageTitle() {
        if (targetRoute === "rules") return "Rules"
        if (targetRoute === "session") return "Session"
        return "Settings"
    }

    function pageSubtitle() {
        if (targetRoute === "rules") return "Window, workspace and layer behavior"
        if (targetRoute === "session") return "Startup and desktop session behavior"
        return "This area is not implemented yet"
    }

    function detailText() {
        if (targetRoute === "rules")
            return "Maho is not exposing a second rule writer until the advanced Hyprland configuration owner is explicit and tested. Existing live rules remain untouched."
        if (targetRoute === "session")
            return "Managed startup editing is deferred until Maho has one tested session configuration writer. Existing startup behavior remains authoritative."
        return "No placeholder controls are exposed because Maho Settings must not invent unsupported system state or mutation authority."
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        PageHeader {
            title: root.pageTitle()
            subtitle: root.pageSubtitle()
            foreground: root.foreground
            muted: root.muted
        }

        StatePanel {
            title: "Not available yet"
            detail: root.detailText()
            surface: root.surface
            borderColor: root.borderColor
            foreground: root.foreground
            muted: root.muted
            accent: root.accent
        }

        Item { Layout.fillHeight: true }
    }
}
