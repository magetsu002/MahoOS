import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property var theme
    property string label: ""
    property string route: ""
    property string iconName: ""
    property bool selected: false
    signal activated(string route)

    width: parent ? parent.width : 220
    height: 35
    radius: 12
    color: root.selected
        ? (hover.hovered ? root.theme.navSelectedHover : root.theme.navSelected)
        : (hover.hovered ? root.theme.navHover : "transparent")
    border.width: root.selected ? 1 : 0
    border.color: root.selected ? root.theme.navSelectedRim : "transparent"
    antialiasing: true

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 11
        anchors.rightMargin: 10
        spacing: 11

        MahoIcon {
            width: 20
            height: 20
            name: root.iconName
            tone: root.theme.textPrimary
            opacity: root.selected ? 0.98 : 0.88
        }

        Text {
            text: root.label
            color: root.selected ? root.theme.textPrimary : root.theme.textBody
            font.pixelSize: 14
            font.weight: root.selected ? Font.Medium : Font.Normal
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            Layout.fillWidth: true
        }
    }

    HoverHandler { id: hover }
    TapHandler { onTapped: root.activated(root.route) }

    Behavior on color {
        ColorAnimation { duration: 110 }
    }
}
