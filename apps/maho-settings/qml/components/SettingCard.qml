import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property color surface: "#211f26"
    property color borderColor: "#3d3942"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property color accent: "#d0bcff"
    property string title: ""
    property string description: ""

    property string headerActionIcon: ""
    property string headerActionLabel: ""
    property bool headerActionEnabled: true
    property bool headerActionEmphasized: false
    signal headerActionTriggered()

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

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            visible: root.title.length > 0
                || root.description.length > 0
                || root.headerActionIcon.length > 0

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Text {
                    text: root.title
                    color: root.foreground
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    visible: text.length > 0
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

            MahoIconButton {
                visible: root.headerActionIcon.length > 0
                Layout.alignment: Qt.AlignTop | Qt.AlignRight
                iconName: root.headerActionIcon
                label: root.headerActionLabel
                emphasized: root.headerActionEmphasized
                enabled: root.headerActionEnabled
                accent: root.accent
                foreground: root.foreground
                muted: root.muted
                onClicked: root.headerActionTriggered()
            }
        }

        ColumnLayout {
            id: slot
            spacing: 10
            Layout.fillWidth: true
        }
    }
}
