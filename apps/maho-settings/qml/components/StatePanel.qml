import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property color surface: "#211f26"
    property color borderColor: "#3d3942"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property color accent: "#d0bcff"
    property string title: "Unavailable"
    property string detail: ""
    property bool retryVisible: false
    signal retryRequested()

    radius: 18
    color: root.surface
    border.width: 1
    border.color: root.borderColor
    implicitHeight: column.implicitHeight + 40
    Layout.fillWidth: true

    ColumnLayout {
        id: column
        anchors.centerIn: parent
        width: Math.min(parent.width - 40, 520)
        spacing: 8

        Text {
            text: root.title
            color: root.foreground
            font.pixelSize: 16
            font.weight: Font.DemiBold
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }

        Text {
            text: root.detail
            color: root.muted
            font.pixelSize: 12
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
            visible: text.length > 0
        }

        Button {
            text: "Retry"
            visible: root.retryVisible
            Layout.alignment: Qt.AlignHCenter
            onClicked: root.retryRequested()
        }
    }
}
