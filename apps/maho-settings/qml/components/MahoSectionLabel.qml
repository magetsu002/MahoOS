import QtQuick
import QtQuick.Layouts

Text {
    id: root

    property color textColor: "#b7aaaa"

    color: root.textColor
    opacity: 0.78
    font.pixelSize: 10
    font.weight: Font.Medium
    font.letterSpacing: 0.7
    font.capitalization: Font.AllUppercase
    Layout.fillWidth: true
    Layout.leftMargin: 11
}
