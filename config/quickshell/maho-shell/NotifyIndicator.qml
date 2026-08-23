import QtQuick

Item {
    id: indicator

    required property var theme
    required property var notifyStatus
    property bool vertical: false

    readonly property int unreadCount: notifyStatus ? notifyStatus.unreadCount : 0
    readonly property bool dndEnabled: notifyStatus ? notifyStatus.dndEnabled : false

    width: vertical ? 26 : (unreadCount > 0 ? 30 : 18)
    height: vertical ? 30 : 28
    visible: notifyStatus ? notifyStatus.active : false
    opacity: unreadCount > 0 || dndEnabled ? 1 : 0.46

    Behavior on opacity { NumberAnimation { duration: 140 } }

    Rectangle {
        anchors.centerIn: parent
        width: indicator.unreadCount > 0 ? 24 : 20
        height: width
        radius: width / 2
        color: indicator.unreadCount > 0
            ? theme.alpha(theme.primary, 0.14)
            : "transparent"
        border.width: indicator.unreadCount > 0 ? 1 : 0
        border.color: theme.alpha(theme.primary, 0.24)

        Text {
            anchors.centerIn: parent
            text: indicator.dndEnabled ? "󰂛" : "󰂚"
            color: indicator.dndEnabled
                ? theme.secondary
                : (indicator.unreadCount > 0 ? theme.primary : theme.muted)
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 12
            textFormat: Text.PlainText

            Behavior on color { ColorAnimation { duration: 180 } }
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.rightMargin: -2
        anchors.topMargin: -1
        width: indicator.unreadCount > 0 ? Math.max(14, countLabel.implicitWidth + 7) : 0
        height: 14
        radius: 7
        visible: indicator.unreadCount > 0
        color: theme.primary
        border.width: 1
        border.color: theme.alpha(theme.surface, 0.72)

        Text {
            id: countLabel
            anchors.centerIn: parent
            text: indicator.unreadCount > 99 ? "99+" : String(indicator.unreadCount)
            color: theme.surface
            font.pixelSize: 7
            font.weight: Font.Bold
            textFormat: Text.PlainText
        }
    }
}
