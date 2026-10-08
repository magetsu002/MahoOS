import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property string title: ""
    property string description: ""
    property string iconName: ""
    property var theme
    property bool interactive: false
    default property alias content: trailing.data
    signal activated()

    Layout.fillWidth: true
    implicitHeight: 94
    radius: 18
    color: root.interactive
        ? (tap.pressed ? root.theme.controlPressed
            : (hover.hovered ? root.theme.rowHover : root.theme.rowFill))
        : root.theme.rowFill
    border.width: 1
    border.color: root.theme.rowRim
    antialiasing: true

    HoverHandler {
        id: hover
        enabled: root.interactive
    }

    TapHandler {
        id: tap
        enabled: root.interactive
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.activated()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        spacing: 16

        MahoIcon {
            Layout.preferredWidth: 28
            Layout.preferredHeight: 28
            name: root.iconName
            tone: root.theme.textPrimary
            opacity: 0.94
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            Text {
                text: root.title
                color: root.theme.textPrimary
                font.pixelSize: 15
                font.weight: Font.Medium
                Layout.fillWidth: true
            }

            Text {
                text: root.description
                color: root.theme.textSecondary
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                Layout.fillWidth: true
            }
        }

        RowLayout {
            id: trailing
            spacing: 8
            Layout.alignment: Qt.AlignVCenter
        }
    }
}
