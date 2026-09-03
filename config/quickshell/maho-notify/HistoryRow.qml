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

    implicitHeight: content.implicitHeight + 20
    radius: 14
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
            GradientStop { position: 0.00; color: theme.alpha(theme.foreground, row.selected ? 0.030 : 0.018) }
            GradientStop { position: 0.26; color: row.critical ? theme.criticalWash : "transparent" }
            GradientStop { position: 1.00; color: theme.alpha(theme.accent, row.unread ? 0.025 : 0.012) }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 1
        anchors.verticalCenter: parent.verticalCenter
        width: 3
        height: Math.min(30, parent.height - 18)
        radius: 2
        visible: row.unread
        color: row.critical ? theme.error : theme.accent
        opacity: row.selected ? 0.96 : 0.72
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
        x: 12
        y: 10
        width: parent.width - 24
        spacing: 10

        AppIcon {
            theme: row.theme
            identityResolver: row.identityResolver
            entry: row.entry
            iconSize: 30
            cornerRadius: 9
            backgroundColor: theme.alpha(row.critical ? theme.error : theme.accent, 0.10)
            foregroundColor: row.critical ? theme.error : theme.accent
        }

        Column {
            width: parent.width - 40
            spacing: 4

            Row {
                width: parent.width
                spacing: 6

                Text {
                    width: parent.width - groupBadge.width - timeLabel.width - 12
                    text: entry.appName || "Notification"
                    color: row.unread ? theme.textPrimary : theme.textSecondary
                    font.pixelSize: 10
                    font.weight: row.unread ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                Rectangle {
                    id: groupBadge
                    width: Number(entry.groupCount || 1) > 1 ? groupText.implicitWidth + 12 : 0
                    height: 18
                    radius: 9
                    visible: Number(entry.groupCount || 1) > 1
                    color: theme.badgeFill
                    border.width: 1
                    border.color: theme.badgeRim

                    Text {
                        id: groupText
                        anchors.centerIn: parent
                        text: String(entry.groupCount) + " grouped"
                        color: theme.textPrimary
                        font.pixelSize: 8
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }
                }

                Text {
                    id: timeLabel
                    text: row.relativeTimestamp
                    color: theme.alpha(theme.muted, 0.68)
                    font.pixelSize: 10
                    textFormat: Text.PlainText
                }
            }

            Text {
                width: parent.width
                text: entry.summary || entry.appName || "Notification"
                color: theme.textPrimary
                font.pixelSize: 12
                font.weight: Font.DemiBold
                maximumLineCount: 1
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }

            Text {
                width: parent.width
                visible: text.length > 0
                text: entry.body || ""
                color: theme.textSecondary
                font.pixelSize: 11
                lineHeight: 1.13
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
                color: theme.alpha(row.critical ? theme.error : theme.accent, 0.84)
                font.pixelSize: 10
                textFormat: Text.PlainText
            }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.top: parent.top
        height: 1
        radius: 1
        color: theme.alpha(theme.foreground, row.selected ? 0.030 : 0.016)
    }
}
