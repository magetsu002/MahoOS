import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property string title: ""
    property string subtitle: ""

    spacing: 5

    Text {
        text: root.title
        color: root.foreground
        font.pixelSize: 28
        font.weight: Font.DemiBold
        Layout.fillWidth: true
    }

    Text {
        text: root.subtitle
        color: root.muted
        font.pixelSize: 13
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        visible: text.length > 0
    }
}
