import QtQuick
import QtQuick.Layouts
import "../components"

Item {
    id: root

    required property var bridge
    required property var themePalette
    property string targetRoute: ""

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        PageHeader {
            title: "Settings"
            subtitle: "This area is not implemented yet"
            foreground: theme.textPrimary
            muted: theme.textSecondary
        }

        Item { Layout.preferredHeight: 6 }

        StatePanel {
            title: "Not available yet"
            detail: "No placeholder controls are exposed because Maho Settings must not invent unsupported system state or mutation authority."
            surface: theme.surfaceElevated
            borderColor: theme.rowRim
            foreground: theme.textPrimary
            muted: theme.textSecondary
            accent: theme.accent
        }

        Item { Layout.fillHeight: true }
    }
}
