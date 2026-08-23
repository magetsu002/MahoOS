import QtQuick
import Quickshell
import Quickshell.Services.Notifications

Rectangle {
    id: row

    required property var theme
    required property var entry
    property bool expanded: false
    readonly property bool unread: Number(entry.groupUnread || 0) > 0
    readonly property bool critical: Number(entry.urgency) === Number(NotificationUrgency.Critical)
    readonly property string iconSource: {
        const icon = entry.icon || ""
        return icon !== "" ? Quickshell.iconPath(icon, "dialog-information") : ""
    }

    implicitHeight: content.implicitHeight + 18
    radius: 12
    color: theme.alpha(
        unread ? theme.primary : theme.foreground,
        historyHover.hovered ? (unread ? 0.12 : 0.06) : (unread ? 0.075 : 0.028)
    )
    border.width: 1
    border.color: theme.alpha(critical ? theme.error : (unread ? theme.primary : theme.outline), critical ? 0.40 : 0.16)

    Behavior on color { ColorAnimation { duration: 130 } }

    HoverHandler { id: historyHover }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: row.expanded = !row.expanded
    }

    Row {
        id: content
        x: 10
        y: 9
        width: parent.width - 20
        spacing: 9

        Item {
            width: 24
            height: 24

            Rectangle {
                anchors.fill: parent
                radius: 7
                color: theme.alpha(critical ? theme.error : theme.primary, 0.13)
                visible: historyIcon.source.toString().length === 0

                Text {
                    anchors.centerIn: parent
                    text: String(entry.appName || "N").slice(0, 1).toUpperCase()
                    color: critical ? theme.error : theme.primary
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    textFormat: Text.PlainText
                }
            }

            Image {
                id: historyIcon
                anchors.fill: parent
                source: row.iconSource
                sourceSize.width: 24
                sourceSize.height: 24
                fillMode: Image.PreserveAspectFit
            }
        }

        Column {
            width: parent.width - 33
            spacing: 3

            Row {
                width: parent.width
                spacing: 6

                Text {
                    width: parent.width - timeLabel.width - 6
                    text: (entry.appName || "Notification")
                        + (Number(entry.groupCount || 1) > 1
                            ? " · " + String(entry.groupCount)
                            : "")
                    color: row.unread ? theme.foreground : theme.muted
                    font.pixelSize: 11
                    font.weight: row.unread ? Font.DemiBold : Font.Medium
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                Text {
                    id: timeLabel
                    text: Qt.formatTime(new Date(Number(entry.timestamp)), "hh:mm")
                    color: theme.alpha(theme.muted, 0.78)
                    font.pixelSize: 10
                    textFormat: Text.PlainText
                }
            }

            Text {
                width: parent.width
                text: entry.summary || entry.appName || "Notification"
                color: theme.foreground
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
                color: theme.muted
                font.pixelSize: 11
                lineHeight: 1.12
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
                color: theme.alpha(critical ? theme.error : theme.primary, 0.86)
                font.pixelSize: 10
                textFormat: Text.PlainText
            }
        }
    }
}
