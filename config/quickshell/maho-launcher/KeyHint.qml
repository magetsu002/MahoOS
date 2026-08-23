import QtQuick
import QtQuick.Layouts

RowLayout {
    id: root

    required property var theme
    property string keyText: ""
    property string label: ""
    spacing: 9

    Rectangle {
        implicitWidth: Math.max(40, keyLabel.implicitWidth + 18)
        implicitHeight: 32
        radius: 7
        color: root.theme.keyChip
        border.width: 1
        border.color: root.theme.keyBorder

        Text {
            id: keyLabel
            anchors.centerIn: parent
            text: root.keyText
            color: root.theme.foreground
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
    }

    Text {
        text: root.label
        color: root.theme.muted
        font.family: "Inter, Noto Sans, sans-serif"
        font.pixelSize: 13
        Layout.alignment: Qt.AlignVCenter
    }
}
