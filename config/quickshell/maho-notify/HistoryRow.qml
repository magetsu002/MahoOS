import QtQuick
import Quickshell.Services.Notifications

Rectangle {
    id: row

    required property var theme
    required property var entry
    required property var identityResolver
    required property var controller
    property string relativeTimestamp: ""
    property bool expanded: false
    property bool menuOpen: false
    readonly property bool unread: Number(entry.groupUnread || 0) > 0
    readonly property bool critical: Number(entry.urgency) === Number(NotificationUrgency.Critical)
    readonly property bool held: Boolean(entry.held)

    signal activated()
    signal menuToggleRequested(string entryId)

    implicitHeight: Math.max(textColumn.implicitHeight, 46) + 32
    radius: 15
    antialiasing: true
    color: row.unread
        ? (historyHover.hovered ? theme.rowUnreadHover : theme.rowUnread)
        : (historyHover.hovered ? theme.rowHover : theme.rowFill)
    border.width: 1
    border.color: row.critical ? theme.criticalRim : theme.rowRim
    scale: historyTap.pressed ? 0.996 : 1
    clip: false
    z: row.menuOpen ? 30 : 0

    Behavior on color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: parent.radius - 1
        antialiasing: true
        color: "transparent"
        gradient: Gradient {
            GradientStop { position: 0.00; color: theme.rowTopWash }
            GradientStop { position: 0.34; color: row.critical ? theme.criticalWash : "transparent" }
            GradientStop { position: 0.72; color: "transparent" }
            GradientStop { position: 1.00; color: theme.rowBottomShade }
        }
    }

    HoverHandler { id: historyHover }
    TapHandler {
        id: historyTap
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: {
            if (row.menuOpen) {
                row.menuToggleRequested(String(entry.id))
                return
            }
            row.activated()
        }
    }

    Item {
        id: content
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 14
        anchors.topMargin: 16
        anchors.bottomMargin: 16

        // Keep every application identity inside one fixed optical lane.
        // Icons with different intrinsic artwork no longer shift the text grid
        // or look high/low relative to multi-line notification copy.
        Item {
            id: iconLane
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 48

            AppIcon {
                id: appIcon
                anchors.centerIn: parent
                theme: row.theme
                identityResolver: row.identityResolver
                entry: row.entry
                iconSize: 44
                cornerRadius: 12
                backgroundColor: theme.alpha(row.critical ? theme.error : theme.accent, 0.10)
                foregroundColor: row.critical ? theme.error : theme.accent
            }
        }

        Column {
            id: textColumn
            anchors.left: iconLane.right
            anchors.leftMargin: 12
            anchors.right: parent.right
            anchors.rightMargin: 64
            anchors.verticalCenter: parent.verticalCenter
            spacing: 3

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
                lineHeight: 1.16
                wrapMode: Text.Wrap
                maximumLineCount: row.expanded ? 6 : 1
                elide: Text.ElideRight
                textFormat: Text.PlainText
            }

            Text {
                width: parent.width
                visible: row.held
                text: entry.holdReason && String(entry.holdReason).length > 0
                    ? "Held · " + String(entry.holdReason)
                    : "Held"
                color: theme.heldTagText
                font.pixelSize: 10
                font.weight: Font.Medium
                textFormat: Text.PlainText
            }

            Text {
                width: parent.width
                visible: Number(entry.groupCount || 1) > 1
                text: String(entry.groupCount) + " grouped"
                color: theme.textFaint
                font.pixelSize: 9
                font.weight: Font.Medium
                textFormat: Text.PlainText
            }
        }

        Text {
            id: timeLabel
            anchors.right: parent.right
            anchors.top: textColumn.top
            text: row.relativeTimestamp
            color: theme.textFaint
            font.pixelSize: 10
            font.weight: Font.Medium
            textFormat: Text.PlainText
        }

        // A stable action lane keeps the hover box geometrically centered and
        // prevents its animation from visually wandering as row text changes.
        Item {
            id: actionLane
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 32

            Rectangle {
                id: menuButton
                anchors.centerIn: parent
                width: 28
                height: 28
                radius: 9
                transformOrigin: Item.Center
                opacity: historyHover.hovered || row.menuOpen ? 1 : 0
                scale: historyHover.hovered || row.menuOpen ? 1 : 0.92
                color: menuMouse.pressed
                    ? theme.controlPressed
                    : (menuMouse.containsMouse || row.menuOpen ? theme.controlHover : "transparent")
                border.width: menuMouse.containsMouse || row.menuOpen ? 1 : 0
                border.color: theme.controlRim

                Behavior on color { ColorAnimation { duration: 110; easing.type: Easing.OutCubic } }
                Behavior on opacity { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: 135; easing.type: Easing.OutCubic } }

                Row {
                    anchors.centerIn: parent
                    spacing: 2

                    Repeater {
                        model: 3

                        Rectangle {
                            width: 3
                            height: 3
                            radius: 1.5
                            color: theme.textSecondary
                        }
                    }
                }

                MouseArea {
                    id: menuMouse
                    anchors.fill: parent
                    enabled: menuButton.opacity > 0.01 || row.menuOpen
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: row.menuToggleRequested(String(entry.id))
                }
            }
        }
    }

    function menuAnchorFor(target) {
        return menuButton.mapToItem(target, menuButton.width / 2, menuButton.height / 2)
    }
}
