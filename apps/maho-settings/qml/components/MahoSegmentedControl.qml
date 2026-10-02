import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property var theme
    property var options: []
    property string currentValue: ""
    signal selected(string value)

    implicitWidth: Math.max(220, options.length * 96)
    implicitHeight: 40
    radius: 12
    color: root.theme.controlFill
    border.width: 1
    border.color: root.theme.controlRim
    antialiasing: true

    RowLayout {
        anchors.fill: parent
        anchors.margins: 1
        spacing: 0

        Repeater {
            model: root.options

            delegate: Rectangle {
                required property var modelData
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 11
                color: root.currentValue === modelData.value
                    ? root.theme.controlActive
                    : (hover.hovered ? root.theme.controlHover : "transparent")

                Text {
                    anchors.centerIn: parent
                    text: modelData.label
                    color: root.currentValue === modelData.value
                        ? root.theme.textPrimary
                        : root.theme.textSecondary
                    font.pixelSize: 12
                    font.weight: root.currentValue === modelData.value ? Font.Medium : Font.Normal
                }

                HoverHandler { id: hover }
                TapHandler { onTapped: root.selected(modelData.value) }

                Behavior on color {
                    ColorAnimation { duration: root.theme.reducedMotion ? 0 : 110 }
                }
            }
        }
    }
}
