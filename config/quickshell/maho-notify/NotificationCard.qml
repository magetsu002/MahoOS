import QtQuick
import Quickshell.Services.Notifications

Rectangle {
    id: card

    required property var theme
    required property var notification
    required property var identityResolver
    property int groupCount: 1
    property bool hovered: hover.hovered
    readonly property bool critical: notification && notification.urgency === NotificationUrgency.Critical
    readonly property int actionCount:
        notification && notification.actions ? Math.min(2, notification.actions.length) : 0
    readonly property int timeoutMs: {
        if (!notification)
            return 7000

        // Quickshell 0.3.1 exposes the freedesktop expiry value in
        // milliseconds, despite older generated docs describing seconds.
        const requested = Math.round(notification.expireTimeout)
        const isCritical = notification.urgency === NotificationUrgency.Critical
        const low = notification.urgency === NotificationUrgency.Low
        const fallback = isCritical ? 14000 : (low ? 4000 : 7000)
        const minimum = isCritical ? 10000 : 3000
        const maximum = isCritical ? 20000 : 12000

        if (requested <= 0)
            return fallback
        return Math.max(minimum, Math.min(maximum, requested))
    }

    signal dismissRequested()
    signal expireRequested()

    implicitHeight: content.implicitHeight + 28
    radius: 19
    antialiasing: true
    color: theme.popupFill
    border.width: 1
    border.color: card.critical ? theme.criticalRim : theme.shellRim
    clip: true
    opacity: 1
    scale: card.hovered ? 1.004 : 1

    Behavior on opacity { NumberAnimation { duration: 155; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        antialiasing: true
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.00; color: theme.shellTopSpecular }
            GradientStop { position: 0.18; color: card.critical ? theme.criticalWash : theme.shellAccentWash }
            GradientStop { position: 0.58; color: "transparent" }
            GradientStop { position: 1.00; color: theme.shellBottomShade }
        }
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.top: parent.top
        anchors.topMargin: 1
        height: 1
        radius: 1
        antialiasing: true
        color: theme.shellInnerLine
    }

    HoverHandler { id: hover }

    Timer {
        id: expiry
        interval: card.timeoutMs
        repeat: false
        running: !card.hovered
        onTriggered: {
            if (card.notification && card.notification.tracked)
                card.expireRequested()
        }
    }

    onHoveredChanged: {
        if (!hovered)
            expiry.restart()
    }

    Column {
        id: content

        x: 15
        y: 14
        width: parent.width - 30
        spacing: 8

        Row {
            width: parent.width
            spacing: 10

            // notification.image is notification content, not application identity.
            AppIcon {
                theme: card.theme
                identityResolver: card.identityResolver
                notification: card.notification
                iconSize: 26
                cornerRadius: 8
            }

            Column {
                width: parent.width - 26 - dismissButton.width - 19
                spacing: 2

                Text {
                    width: parent.width
                    text: (notification.appName || "Notification")
                        + (card.groupCount > 1 ? "  ·  " + String(card.groupCount) + " grouped" : "")
                    color: theme.textSecondary
                    font.pixelSize: 11
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                Text {
                    width: parent.width
                    text: notification.summary || notification.appName || "Notification"
                    color: theme.textPrimary
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    maximumLineCount: 2
                    wrapMode: Text.Wrap
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }
            }

            Rectangle {
                id: dismissButton

                width: 27
                height: 27
                radius: 10
                antialiasing: true
                color: dismissTap.pressed
                    ? theme.controlPressed
                    : (dismissHover.hovered ? theme.controlHover : "transparent")
                border.width: dismissHover.hovered || dismissTap.pressed ? 1 : 0
                border.color: theme.controlRim
                scale: dismissTap.pressed ? 0.96 : 1

                Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

                Text {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: -1
                    text: "×"
                    color: theme.textSecondary
                    font.pixelSize: 17
                    textFormat: Text.PlainText
                }

                HoverHandler { id: dismissHover }
                TapHandler {
                    id: dismissTap
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: card.dismissRequested()
                }
            }
        }

        Text {
            width: parent.width
            visible: text.length > 0
            text: notification.body || ""
            color: theme.textBody
            font.pixelSize: 12
            lineHeight: 1.20
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

                    width: Math.min(142, Math.max(78, actionLabel.implicitWidth + 26))
                    height: 31
                    radius: 11
                    antialiasing: true
                    color: actionTap.pressed
                        ? theme.controlPressed
                        : (actionHover.hovered ? theme.actionHover : theme.actionFill)
                    border.width: 1
                    border.color: actionHover.hovered ? theme.controlRimActive : theme.actionRim
                    scale: actionTap.pressed ? 0.978 : 1

                    Behavior on color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
                    Behavior on border.color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

                    Text {
                        id: actionLabel
                        anchors.centerIn: parent
                        width: parent.width - 16
                        text: notification.actions[index].text
                        color: theme.textPrimary
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }

                    HoverHandler { id: actionHover }
                    TapHandler {
                        id: actionTap
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: notification.actions[index].invoke()
                    }
                }
            }
        }
    }
}
