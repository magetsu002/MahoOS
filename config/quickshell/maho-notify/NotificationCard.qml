import QtQuick
import Quickshell
import Quickshell.Services.Notifications

Rectangle {
    id: card

    required property var theme
    required property var notification
    property bool hovered: hover.hovered
    readonly property int actionCount:
        notification && notification.actions ? Math.min(2, notification.actions.length) : 0
    readonly property int timeoutMs: {
        if (!notification)
            return 7000

        // Quickshell 0.3.1 exposes the freedesktop expiry value in
        // milliseconds, despite older generated docs describing seconds.
        const requested = Math.round(notification.expireTimeout)
        const critical = notification.urgency === NotificationUrgency.Critical
        const low = notification.urgency === NotificationUrgency.Low
        const fallback = critical ? 14000 : (low ? 4000 : 7000)
        const minimum = critical ? 10000 : 3000
        const maximum = critical ? 20000 : 12000

        if (requested <= 0)
            return fallback
        return Math.max(minimum, Math.min(maximum, requested))
    }

    signal dismissRequested()

    implicitHeight: content.implicitHeight + 22
    radius: 14
    color: theme.alpha(theme.surfaceHigh, 0.965)
    border.width: 1
    border.color: theme.alpha(
        notification.urgency === NotificationUrgency.Critical ? theme.error : theme.outline,
        notification.urgency === NotificationUrgency.Critical ? 0.48 : 0.24
    )
    opacity: 1

    Behavior on opacity { NumberAnimation { duration: 140 } }

    HoverHandler { id: hover }

    Timer {
        id: expiry
        interval: card.timeoutMs
        repeat: false
        running: !card.hovered
        onTriggered: {
            if (card.notification && card.notification.tracked)
                card.notification.expire()
        }
    }

    onHoveredChanged: {
        if (!hovered)
            expiry.restart()
    }

    Column {
        id: content

        x: 12
        y: 11
        width: parent.width - 24
        spacing: 6

        Row {
            width: parent.width
            spacing: 8

            Item {
                width: 26
                height: 26

                Rectangle {
                    anchors.fill: parent
                    radius: 8
                    color: theme.alpha(theme.primary, 0.13)
                    visible: appImage.source.toString().length === 0

                    Text {
                        anchors.centerIn: parent
                        text: (notification.appName || "N").slice(0, 1).toUpperCase()
                        color: theme.primary
                        font.pixelSize: 12
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }
                }

                Image {
                    id: appImage
                    anchors.fill: parent
                    sourceSize.width: 26
                    sourceSize.height: 26
                    fillMode: Image.PreserveAspectFit
                    source: notification.image !== ""
                        ? notification.image
                        : (notification.appIcon !== ""
                            ? Quickshell.iconPath(notification.appIcon, "dialog-information")
                            : "")
                }
            }

            Column {
                width: parent.width - 26 - dismissButton.width - 16
                spacing: 1

                Text {
                    width: parent.width
                    text: notification.appName || "Notification"
                    color: theme.muted
                    font.pixelSize: 11
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                Text {
                    width: parent.width
                    text: notification.summary || notification.appName || "Notification"
                    color: theme.foreground
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    maximumLineCount: 2
                    wrapMode: Text.Wrap
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }
            }

            Rectangle {
                id: dismissButton

                width: 24
                height: 24
                radius: 8
                color: dismissHover.hovered
                    ? theme.alpha(theme.foreground, 0.09)
                    : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: theme.muted
                    font.pixelSize: 17
                    textFormat: Text.PlainText
                }

                HoverHandler { id: dismissHover }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: card.dismissRequested()
                }
            }
        }

        Text {
            width: parent.width
            visible: text.length > 0
            text: notification.body || ""
            color: theme.muted
            font.pixelSize: 12
            lineHeight: 1.14
            wrapMode: Text.Wrap
            maximumLineCount: 3
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }

        Row {
            width: parent.width
            spacing: 7
            visible: card.actionCount > 0

            Repeater {
                model: card.actionCount

                Rectangle {
                    required property int index

                    width: Math.min(136, Math.max(72, actionLabel.implicitWidth + 22))
                    height: 28
                    radius: 9
                    color: actionHover.hovered
                        ? theme.alpha(theme.primary, 0.20)
                        : theme.alpha(theme.primary, 0.11)
                    border.width: 1
                    border.color: theme.alpha(theme.primary, 0.25)

                    Text {
                        id: actionLabel
                        anchors.centerIn: parent
                        width: parent.width - 16
                        text: notification.actions[index].text
                        color: theme.primary
                        font.pixelSize: 11
                        font.weight: Font.Medium
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }

                    HoverHandler { id: actionHover }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: notification.actions[index].invoke()
                    }
                }
            }
        }
    }
}
