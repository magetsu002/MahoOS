import QtQuick
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    property string targetRoute: ""

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

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
        spacing: 12

        PageHeader {
            title: root.pageTitle()
            subtitle: root.pageSubtitle()
            foreground: theme.textPrimary
            muted: theme.textSecondary
        }

        Item { Layout.preferredHeight: 6 }

        StatePanel {
            title: "Not available yet"
            detail: root.detailText()
            surface: theme.surfaceElevated
            borderColor: theme.rowRim
            foreground: theme.textPrimary
            muted: theme.textSecondary
            accent: theme.accent
        }

        Item { Layout.fillHeight: true }
    }
}
