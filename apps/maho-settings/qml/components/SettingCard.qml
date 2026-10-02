import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    property color surface: "#211f26"
    property color borderColor: "#3d3942"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property string title: ""
    property string description: ""
    default property alias content: slot.data

    radius: 18
    color: Qt.rgba(root.surface.r, root.surface.g, root.surface.b, 0.58)
    border.width: 1
    border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.075)
    implicitHeight: contentColumn.implicitHeight + 32
    Layout.fillWidth: true

    ColumnLayout {
        id: contentColumn
        anchors.fill: parent
        anchors.margins: 16
        spacing: 12

        ColumnLayout {
            spacing: 3
            Layout.fillWidth: true
            visible: root.title.length > 0 || root.description.length > 0

            Text {
                text: root.title
                color: root.foreground
                font.pixelSize: 15
                font.weight: Font.DemiBold
                Layout.fillWidth: true
            }

            Text {
                text: root.description
                color: root.muted
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
                visible: text.length > 0
            }
        }

        ColumnLayout {
            id: slot
            spacing: 10
            Layout.fillWidth: true
        }
    }
}
