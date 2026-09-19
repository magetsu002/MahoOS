import QtQuick

Rectangle {
    id: card

    required property var theme
    required property var entry
    required property var identityResolver
    property bool hovered: replayHover.hovered

    signal dismissRequested()
    signal activated()

    implicitHeight: content.implicitHeight + 28
    radius: 19
    antialiasing: true
    color: theme.popupFill
    border.width: 1
    border.color: theme.shellRim
    clip: true
    scale: replayTap.pressed ? 0.996 : (card.hovered ? 1.004 : 1)

    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        antialiasing: true
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.00; color: theme.shellTopSpecular }
            GradientStop { position: 0.18; color: theme.shellAccentWash }
            GradientStop { position: 0.58; color: "transparent" }
            GradientStop { position: 1.00; color: theme.shellBottomShade }
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: parent.radius
        antialiasing: true
        color: "transparent"
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.00; color: "transparent" }
            GradientStop { position: 0.18; color: theme.shellLiquidSheen }
            GradientStop { position: 0.42; color: "transparent" }
            GradientStop { position: 0.78; color: theme.shellLiquidTint }
            GradientStop { position: 1.00; color: "transparent" }
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
        antialiasing: true
        color: theme.shellInnerLine
    }

    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.leftMargin: 24
        anchors.rightMargin: 24
        anchors.bottom: parent.bottom
        height: 1
        radius: 1
        antialiasing: true
        color: theme.alpha(theme.accent, 0.025)
    }

    HoverHandler { id: replayHover }
    TapHandler {
        id: replayTap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: {
            if (!dismissHover.hovered)
                card.activated()
        }
    }

    Timer {
        id: expiry
        interval: 7000
        repeat: false
        running: !card.hovered
        onTriggered: card.dismissRequested()
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

            AppIcon {
                id: replayIcon
                theme: card.theme
                identityResolver: card.identityResolver
                entry: card.entry
                iconSize: 26
                cornerRadius: 8
            }

            Column {
                width: parent.width - 26 - dismissButton.width - 19
                spacing: 2

                Text {
                    width: parent.width
                    text: entry.appName || "Notification"
                    color: theme.textSecondary
                    font.pixelSize: 11
                    font.weight: Font.Medium
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                }

                Text {
                    width: parent.width
                    text: entry.summary || entry.appName || "Notification"
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
            text: entry.body || ""
            color: theme.textBody
            font.pixelSize: 12
            lineHeight: 1.20
            wrapMode: Text.Wrap
            maximumLineCount: 3
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }
    }
}
