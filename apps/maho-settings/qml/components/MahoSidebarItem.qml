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
    color: tap.pressed
        ? (root.selected ? root.theme.navSelectedHover : root.theme.navPressed)
        : root.selected
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
            Layout.preferredWidth: 20
            Layout.preferredHeight: 20
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
    TapHandler {
        id: tap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.activated(root.route)
    }
}
