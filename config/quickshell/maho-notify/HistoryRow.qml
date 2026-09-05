import QtQuick
import Quickshell.Services.Notifications

Rectangle {
    id: row

    required property var theme
    required property var entry
    required property var identityResolver
    property string relativeTimestamp: ""
    property bool selected: false
    property bool expanded: false
    readonly property bool unread: Number(entry.groupUnread || 0) > 0
    readonly property bool critical: Number(entry.urgency) === Number(NotificationUrgency.Critical)

    signal activated()

    implicitHeight: content.implicitHeight + 24
    radius: 16
    antialiasing: true
    color: row.selected
        ? theme.rowSelected
        : (row.unread
            ? (historyHover.hovered ? theme.rowUnreadHover : theme.rowUnread)
            : (historyHover.hovered ? theme.rowHover : theme.rowFill))
    border.width: 1
    border.color: row.critical
        ? theme.criticalRim
        : (row.selected || row.unread ? theme.rowActiveRim : theme.rowRim)
    scale: historyTap.pressed ? 0.994 : 1
    clip: true

    Behavior on color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 115; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        antialiasing: true
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.00; color: theme.alpha(theme.foreground, row.selected ? 0.040 : 0.025) }
            GradientStop { position: 0.24; color: row.critical ? theme.criticalWash : "transparent" }
            GradientStop { position: 0.66; color: "transparent" }
            GradientStop { position: 1.00; color: theme.alpha(theme.background, 0.075) }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 1
        anchors.verticalCenter: parent.verticalCenter
        width: 3
        height: Math.min(34, parent.height - 20)
        radius: 2
        visible: row.unread
        color: row.critical ? theme.error : theme.accent
        opacity: row.selected ? 0.96 : 0.80
    }

    HoverHandler { id: historyHover }
    TapHandler {
        id: historyTap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: {
            row.expanded = !row.expanded
            row.activated()
        }
    }

    Row {
        id: content
        x: 14
        y: 12
        width: parent.width - 28
        spacing: 11

        AppIcon {
            theme: row.theme
            identityResolver: row.identityResolver
            entry: row.entry
            iconSize: 32
            cornerRadius: 10
            backgroundColor: theme.alpha(row.critical ? theme.error : theme.accent, 0.11)
            foregroundColor: row.critical ? theme.error : theme.accent
        }

        Column {
            width: parent.width - 43
            spacing: 5

            Row {
                width: parent.width
                spacing: 7

                Text {
                    width: parent.width - groupBadge.width - timeLabel.width - unreadDot.width - 21
                    text: entry.appName || "Notification"
                    color: row.unread ? theme.textSecondary : theme.textMuted
                    font.pixelSize: 11
                    font.weight: row.unread ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                Rectangle {
                    id: groupBadge
                    width: Number(entry.groupCount || 1) > 1 ? groupText.implicitWidth + 14 : 0
                    height: 20
                    radius: 10
                    visible: Number(entry.groupCount || 1) > 1
                    color: theme.badgeFill
                    border.width: 1
                    border.color: theme.badgeRim

                    Text {
                        id: groupText
                        anchors.centerIn: parent
                        text: String(entry.groupCount) + " grouped"
                        color: theme.textPrimary
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }
                }

                Text {
                    id: timeLabel
                    text: row.relativeTimestamp
                    color: theme.textMuted
                    font.pixelSize: 10
                    font.weight: Font.Medium
                    textFormat: Text.PlainText
                }

                Rectangle {
                    id: unreadDot
                    anchors.verticalCenter: parent.verticalCenter
                    width: row.unread ? 6 : 0
                    height: 6
                    radius: 3
                    visible: row.unread
                    color: row.critical ? theme.error : theme.accent
                    opacity: 0.90
                }
            }

            Text {
                width: parent.width
                text: entry.summary || entry.appName || "Notification"
                color: theme.textPrimary
                font.pixelSize: 13
                font.weight: Font.DemiBold
                maximumLineCount: 1
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }

            Text {
                width: parent.width
                visible: text.length > 0
                text: entry.body || ""
                color: theme.textBody
                font.pixelSize: 11
                lineHeight: 1.18
                wrapMode: Text.Wrap
                maximumLineCount: row.expanded ? 8 : 2
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }

            Text {
                width: parent.width
                visible: Number(entry.replacementCount || 0) > 0
                    || Number(entry.groupUnread || 0) > 1
                text: Number(entry.replacementCount || 0) > 0
                    ? "Updated " + String(entry.replacementCount) + "×"
                    : String(entry.groupUnread) + " unread in group"
                color: theme.alpha(row.critical ? theme.error : theme.accent, 0.90)
                font.pixelSize: 10
                font.weight: Font.Medium
                textFormat: Text.PlainText
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.top: parent.top
        height: 1
        radius: 1
        color: theme.alpha(theme.foreground, row.selected ? 0.040 : 0.024)
    }
}
