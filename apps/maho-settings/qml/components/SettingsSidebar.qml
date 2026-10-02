import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property var model: []
    property string currentRoute: "appearance"
    property color surface: "#211f26"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property color accent: "#d0bcff"
    property color borderColor: "#3d3942"
    signal routeSelected(string route)

    color: root.surface
    radius: 20
    border.width: 1
    border.color: root.borderColor

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 4

        Repeater {
            model: root.model

            delegate: Rectangle {
                required property var modelData
                Layout.fillWidth: true
                implicitHeight: 44
                radius: 13
                color: root.currentRoute === modelData.route
                    ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.13)
                    : (hover.hovered
                        ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.055)
                        : "transparent")

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 10

                    Rectangle {
                        width: 25
                        height: 25
                        radius: 8
                        color: root.currentRoute === modelData.route
                            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.17)
                            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.055)

                        Text {
                            anchors.centerIn: parent
                            text: modelData.glyph
                            color: root.currentRoute === modelData.route ? root.accent : root.muted
                            font.pixelSize: 11
                            font.weight: Font.DemiBold
                        }
                    }

                    Text {
                        text: modelData.label
                        color: root.currentRoute === modelData.route ? root.foreground : root.muted
                        font.pixelSize: 13
                        font.weight: root.currentRoute === modelData.route ? Font.DemiBold : Font.Medium
                        Layout.fillWidth: true
                    }
                }

                HoverHandler { id: hover }
                TapHandler { onTapped: root.routeSelected(modelData.route) }
            }
        }

        Item { Layout.fillHeight: true }

        Text {
            text: "MahoOS Settings"
            color: root.muted
            opacity: 0.55
            font.pixelSize: 10
            Layout.leftMargin: 10
            Layout.bottomMargin: 4
        }
    }
}
