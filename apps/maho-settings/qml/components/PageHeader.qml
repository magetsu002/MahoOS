import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root

    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property string title: ""
    property string subtitle: ""

    spacing: 6

    Text {
        text: root.title
        color: root.foreground
        font.pixelSize: 34
        font.weight: Font.Medium
        font.letterSpacing: -0.45
        Layout.fillWidth: true
    }

    Text {
        text: root.subtitle
        color: root.muted
        opacity: 0.84
        font.pixelSize: 14
        font.weight: Font.Normal
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        visible: text.length > 0
    }
}
