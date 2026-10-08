import QtQuick
import QtQuick.Layouts

Item {
    id: root

    property string title: ""
    property string description: ""
    property string trailingText: ""
    property color foreground: "#f4eeee"
    property color muted: "#aaa3a3"
    property bool dividerVisible: true
    default property alias content: trailing.data

    Layout.fillWidth: true
    implicitHeight: description.length > 0 ? 62 : 50

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 2
        anchors.rightMargin: 2
        spacing: 14

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            Text {
                text: root.title
                color: root.foreground
                font.pixelSize: 13
                font.weight: Font.Medium
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            Text {
                visible: text.length > 0
                text: root.description
                color: root.muted
                opacity: 0.84
                font.pixelSize: 11
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }

        Text {
            visible: text.length > 0
            text: root.trailingText
            color: root.muted
            opacity: 0.78
            font.pixelSize: 10
            horizontalAlignment: Text.AlignRight
            Layout.maximumWidth: 150
            elide: Text.ElideRight
        }

        RowLayout {
            id: trailing
            spacing: 6
            Layout.alignment: Qt.AlignVCenter
        }
    }

    Rectangle {
        visible: root.dividerVisible
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 1
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.055)
    }
}
