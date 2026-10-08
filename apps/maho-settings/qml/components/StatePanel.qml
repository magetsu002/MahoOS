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
    color: Qt.rgba(root.surface.r, root.surface.g, root.surface.b, 0.62)
    border.width: 1
    border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.08)
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
            id: retryButton
            text: "Retry"
            visible: root.retryVisible
            Layout.alignment: Qt.AlignHCenter
            implicitHeight: 34
            leftPadding: 15
            rightPadding: 15
            hoverEnabled: true
            contentItem: Text {
                text: retryButton.text
                color: root.foreground
                font.pixelSize: 12
                font.weight: Font.Medium
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
            }
            background: Rectangle {
                radius: 10
                color: retryButton.down
                    ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.13)
                    : retryButton.hovered
                        ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
                        : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.06)
                border.width: 1
                border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
            }
            onClicked: root.retryRequested()
        }
    }
}
