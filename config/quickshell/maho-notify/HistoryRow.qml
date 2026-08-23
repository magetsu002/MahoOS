import QtQuick
import Quickshell
import Quickshell.Services.Notifications

Rectangle {
    id: row

    required property var theme
    required property var entry
    property string relativeTimestamp: ""
    property bool selected: false
    property bool expanded: false
    readonly property bool unread: Number(entry.groupUnread || 0) > 0
    readonly property bool critical: Number(entry.urgency) === Number(NotificationUrgency.Critical)
    readonly property string iconSource: {
        const icon = entry.icon || ""
        return icon !== "" ? Quickshell.iconPath(icon, "dialog-information") : ""
    }

    signal activated()

    implicitHeight: content.implicitHeight + 20
    radius: 14
    color: theme.alpha(
        unread ? theme.primary : theme.surfaceHighest,
        historyHover.hovered || selected ? (unread ? 0.14 : 0.42) : (unread ? 0.075 : 0.22)
    )
    border.width: 1
    border.color: theme.alpha(
        critical ? theme.error : (selected || unread ? theme.primary : theme.outline),
        critical ? 0.42 : (selected ? 0.42 : (unread ? 0.22 : 0.12))
    )

    Behavior on color { ColorAnimation { duration: 130 } }
    Behavior on border.color { ColorAnimation { duration: 130 } }

    Rectangle {
        anchors.left: parent.left
        anchors.leftMargin: 1
        anchors.verticalCenter: parent.verticalCenter
        width: 3
        height: Math.min(30, parent.height - 18)
        radius: 2
        visible: row.unread
        color: critical ? theme.error : theme.primary
        opacity: row.selected ? 0.96 : 0.72
    }

    HoverHandler { id: historyHover }
    TapHandler {
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

        Item {
            width: 30
            height: 30

            Rectangle {
                anchors.fill: parent
                radius: 9
                color: theme.alpha(critical ? theme.error : theme.primary, 0.13)
                visible: historyIcon.source.toString().length === 0

                Text {
                    anchors.centerIn: parent
                    text: String(entry.appName || "N").slice(0, 1).toUpperCase()
                    color: critical ? theme.error : theme.primary
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                    textFormat: Text.PlainText
                }
            }

            Image {
                id: historyIcon
                anchors.fill: parent
                source: row.iconSource
                sourceSize.width: 30
                sourceSize.height: 30
                fillMode: Image.PreserveAspectFit
            }
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
                    color: row.unread ? theme.foreground : theme.muted
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
                    color: theme.alpha(theme.primary, 0.12)
                    border.width: 1
                    border.color: theme.alpha(theme.primary, 0.20)

                    Text {
                        id: groupText
                        anchors.centerIn: parent
                        text: String(entry.groupCount) + " grouped"
                        color: theme.primary
                        font.pixelSize: 8
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }
                }

                Text {
                    id: timeLabel
                    text: row.relativeTimestamp
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

    Rectangle {
        anchors.fill: parent
        anchors.margins: 3
        radius: 11
        color: "transparent"
        border.width: row.selected ? 1 : 0
        border.color: theme.alpha(theme.primary, 0.26)
    }
}
