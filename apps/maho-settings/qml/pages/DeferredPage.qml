import QtQuick
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var palette
    property string targetRoute: ""
    readonly property color foreground: palette ? palette.foreground : "#f3eef8"
    readonly property color muted: palette ? palette.muted : "#aaa3af"
    readonly property color accent: palette ? palette.accent : "#d0bcff"
    readonly property color surface: palette ? palette.surfaceElevated : "#2b2930"
    readonly property color borderColor: palette ? palette.border : "#3d3942"

    ColumnLayout {
        anchors.fill: parent
        spacing: 14

        PageHeader {
            title: "Settings"
            subtitle: "This route is part of the V1 navigation architecture but is not implemented in the foundation milestone."
            foreground: root.foreground
            muted: root.muted
        }

        StatePanel {
            title: "Deferred"
            detail: "No placeholder controls are exposed because Maho Settings must not invent unsupported system state or mutation authority."
            surface: root.surface
            borderColor: root.borderColor
            foreground: root.foreground
            muted: root.muted
            accent: root.accent
        }

        Item { Layout.fillHeight: true }
    }
}
