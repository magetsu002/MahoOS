import QtQuick

Item {
    id: center

    required property var theme
    required property var historyModel
    required property var identityResolver
    required property real availableHeight
    property bool shown: false
    property date timeReference: new Date()

    signal closeRequested()

    width: 432
    height: Math.min(704, Math.max(360, availableHeight - 40))
    focus: shown
    opacity: shown ? 1 : 0
    scale: shown ? 1 : 0.992
    transform: Translate {
        x: center.shown ? 0 : 18
        Behavior on x {
            NumberAnimation { duration: center.shown ? 210 : 155; easing.type: Easing.OutCubic }
        }
    }

    Behavior on opacity {
        NumberAnimation { duration: center.shown ? 210 : 155; easing.type: Easing.OutCubic }
    }
    Behavior on scale {
        NumberAnimation { duration: center.shown ? 210 : 155; easing.type: Easing.OutCubic }
    }

    function relativeTimestamp(timestamp) {
        const ageSeconds = Math.max(0, Math.floor((timeReference.getTime() - Number(timestamp)) / 1000))
        if (ageSeconds < 45)
            return "now"
        if (ageSeconds < 3600)
            return String(Math.floor(ageSeconds / 60)) + "m"
        if (ageSeconds < 86400)
            return String(Math.floor(ageSeconds / 3600)) + "h"
        return Qt.formatDate(new Date(Number(timestamp)), "MMM d")
    }

    function selectOffset(offset) {
        if (historyList.count <= 0)
            return
        historyList.currentIndex = Math.max(0, Math.min(historyList.count - 1, historyList.currentIndex + offset))
        historyList.positionViewAtIndex(historyList.currentIndex, ListView.Contain)
    }

    Keys.onEscapePressed: center.closeRequested()
    Keys.onPressed: event => {
        if (event.key === Qt.Key_D) {
            historyModel.toggleDnd()
            event.accepted = true
        } else if (event.key === Qt.Key_R) {
            historyModel.markAllRead()
            event.accepted = true
        } else if (event.key === Qt.Key_Delete) {
            historyModel.clearRead()
            event.accepted = true
        } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
            selectOffset(1)
            event.accepted = true
        } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
            selectOffset(-1)
            event.accepted = true
        } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Space)
                   && historyList.currentItem) {
            historyList.currentItem.expanded = !historyList.currentItem.expanded
            event.accepted = true
        }
    }

    Timer {
        interval: 60000
        repeat: true
        running: center.shown
        onTriggered: center.timeReference = new Date()
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: -5
        radius: 27
        antialiasing: true
        color: theme.outerGlow
        border.width: 1
        border.color: theme.alpha(theme.accent, 0.045)
    }

    Rectangle {
        id: material
        anchors.fill: parent
        radius: 22
        antialiasing: true
        color: theme.centerFill
        border.width: 1
        border.color: theme.shellRim
        clip: true

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
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 22
            anchors.rightMargin: 22
            anchors.top: parent.top
            height: 1
            radius: 1
            color: theme.shellInnerLine
        }

        Column {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 10

            Item {
                width: parent.width
                height: 52

                Rectangle {
                    id: mark
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    width: 34
                    height: 34
                    radius: 12
                    antialiasing: true
                    color: theme.badgeFill
                    border.width: 1
                    border.color: theme.badgeRim

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 9
                        anchors.rightMargin: 9
                        anchors.top: parent.top
                        height: 1
                        radius: 1
                        color: theme.alpha(theme.foreground, 0.070)
                    }

                    Text {
                        anchors.centerIn: parent
                        text: "󰂚"
                        color: theme.accent
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 15
                        textFormat: Text.PlainText
                    }
                }

                Column {
                    anchors.left: mark.right
                    anchors.leftMargin: 11
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width - mark.width - unreadBadge.width - closeButton.width - 38
                    spacing: 2

                    Text {
                        width: parent.width
                        text: "Notifications"
                        color: theme.textPrimary
                        font.pixelSize: 19
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }

                    Text {
                        width: parent.width
                        text: historyModel.retainedCount > 0
                            ? String(historyModel.retainedCount) + " retained"
                            : "Maho Notify"
                        color: theme.textSecondary
                        font.pixelSize: 10
                        font.weight: Font.Medium
                        textFormat: Text.PlainText
                    }
                }

                Rectangle {
                    id: unreadBadge
                    anchors.right: closeButton.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: historyModel.unreadCount > 0 ? unreadText.implicitWidth + 18 : 0
                    height: 25
                    radius: 13
                    visible: historyModel.unreadCount > 0
                    color: theme.badgeFill
                    border.width: 1
                    border.color: theme.badgeRim

                    Text {
                        id: unreadText
                        anchors.centerIn: parent
                        text: String(historyModel.unreadCount) + " unread"
                        color: theme.textPrimary
                        font.pixelSize: 9
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }
                }

                Rectangle {
                    id: closeButton
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 30
                    height: 30
                    radius: 10
                    antialiasing: true
                    color: closeTap.pressed
                        ? theme.controlPressed
                        : (closeHover.hovered ? theme.controlHover : "transparent")
                    border.width: closeHover.hovered || closeTap.pressed ? 1 : 0
                    border.color: theme.controlRim
                    scale: closeTap.pressed ? 0.96 : 1

                    Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
                    Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

                    Text {
                        anchors.centerIn: parent
                        anchors.verticalCenterOffset: -1
                        text: "×"
                        color: theme.textSecondary
                        font.pixelSize: 18
                        textFormat: Text.PlainText
                    }

                    HoverHandler { id: closeHover }
                    TapHandler { id: closeTap; onTapped: center.closeRequested() }
                }
            }

            Item {
                id: toolbar
                width: parent.width
                height: 42

                Rectangle {
                    anchors.fill: parent
                    radius: 14
                    antialiasing: true
                    color: theme.toolbarFill
                    border.width: 1
                    border.color: theme.toolbarRim

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 16
                        anchors.rightMargin: 16
                        anchors.top: parent.top
                        height: 1
                        radius: 1
                        color: theme.alpha(theme.foreground, 0.045)
                    }
                }

                Row {
                    anchors.fill: parent
                    anchors.margins: 6
                    spacing: 7

                    Rectangle {
                        id: dndButton
                        width: dndLabel.implicitWidth + 28
                        height: 30
                        radius: 12
                        antialiasing: true
                        color: dndTap.pressed
                            ? theme.controlPressed
                            : (historyModel.dndEnabled
                                ? (dndHover.hovered ? theme.actionHover : theme.actionFill)
                                : (dndHover.hovered ? theme.controlHover : theme.controlFill))
                        border.width: 1
                        border.color: historyModel.dndEnabled ? theme.controlRimActive : theme.controlRim
                        scale: dndTap.pressed ? 0.98 : 1

                        Row {
                            anchors.centerIn: parent
                            spacing: 6

                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: 6
                                height: 6
                                radius: 3
                                color: historyModel.dndEnabled ? theme.accent : theme.textSecondary
                            }
                            Text {
                                id: dndLabel
                                anchors.verticalCenter: parent.verticalCenter
                                text: historyModel.dndEnabled ? "DND On" : "DND Off"
                                color: historyModel.dndEnabled ? theme.textPrimary : theme.textSecondary
                                font.pixelSize: 10
                                font.weight: Font.Medium
                                textFormat: Text.PlainText
                            }
                        }

                        Behavior on color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
                        Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
                        HoverHandler { id: dndHover }
                        TapHandler { id: dndTap; onTapped: historyModel.toggleDnd() }
                    }

                    Item {
                        width: Math.max(0, parent.width - dndButton.width - markRead.width - clearRead.width - clearAll.width - 28)
                        height: 1
                    }

                    Rectangle {
                        id: markRead
                        width: markReadText.implicitWidth + 18
                        height: 30
                        radius: 11
                        antialiasing: true
                        color: markReadTap.pressed ? theme.controlPressed : (markReadHover.hovered ? theme.controlHover : "transparent")
                        Text { id: markReadText; anchors.centerIn: parent; text: "Read all"; color: theme.textSecondary; font.pixelSize: 10; font.weight: Font.Medium }
                        Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
                        HoverHandler { id: markReadHover }
                        TapHandler { id: markReadTap; onTapped: historyModel.markAllRead() }
                    }

                    Rectangle {
                        id: clearRead
                        width: clearReadText.implicitWidth + 18
                        height: 30
                        radius: 11
                        antialiasing: true
                        color: clearReadTap.pressed ? theme.controlPressed : (clearReadHover.hovered ? theme.controlHover : "transparent")
                        Text { id: clearReadText; anchors.centerIn: parent; text: "Clear read"; color: theme.textSecondary; font.pixelSize: 10; font.weight: Font.Medium }
                        Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
                        HoverHandler { id: clearReadHover }
                        TapHandler { id: clearReadTap; onTapped: historyModel.clearRead() }
                    }

                    Rectangle {
                        id: clearAll
                        width: clearAllText.implicitWidth + 18
                        height: 30
                        radius: 11
                        antialiasing: true
                        color: clearAllTap.pressed
                            ? theme.alpha(theme.error, 0.15)
                            : (clearAllHover.hovered ? theme.alpha(theme.error, 0.09) : "transparent")
                        Text { id: clearAllText; anchors.centerIn: parent; text: "Clear"; color: clearAllHover.hovered ? theme.error : theme.textSecondary; font.pixelSize: 10; font.weight: Font.Medium }
                        Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
                        HoverHandler { id: clearAllHover }
                        TapHandler { id: clearAllTap; onTapped: historyModel.clearHistory() }
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: 1
                color: theme.divider
            }

            Item {
                id: historyWell
                width: parent.width
                height: parent.height - 52 - 42 - 1 - 30

                Rectangle {
                    anchors.fill: parent
                    radius: 17
                    antialiasing: true
                    color: theme.sectionFill
                    border.width: 1
                    border.color: theme.rowRim

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 18
                        anchors.rightMargin: 18
                        anchors.top: parent.top
                        height: 1
                        radius: 1
                        color: theme.alpha(theme.foreground, 0.032)
                    }
                }

                ListView {
                    id: historyList
                    anchors.fill: parent
                    anchors.margins: 5
                    clip: true
                    spacing: 8
                    reuseItems: true
                    cacheBuffer: 520
                    boundsBehavior: Flickable.StopAtBounds
                    keyNavigationEnabled: true
                    highlightMoveDuration: 120
                    model: historyModel.groupedEntries

                    section.property: "section"
                    section.criteria: ViewSection.FullString
                    section.delegate: Item {
                        required property string section
                        width: historyList.width
                        height: 31

                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 7
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 7
                            text: parent.section
                            color: theme.textSecondary
                            font.pixelSize: 10
                            font.weight: Font.DemiBold
                            font.capitalization: Font.AllUppercase
                            font.letterSpacing: 0.7
                            textFormat: Text.PlainText
                        }
                    }

                    delegate: HistoryRow {
                        required property var modelData
                        required property int index
                        width: historyList.width
                        theme: center.theme
                        identityResolver: center.identityResolver
                        entry: modelData
                        relativeTimestamp: center.relativeTimestamp(modelData.timestamp)
                        selected: historyList.currentIndex === index && center.activeFocus
                        onActivated: historyList.currentIndex = index
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    visible: historyModel.retainedCount === 0

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 44
                        height: 44
                        radius: 16
                        antialiasing: true
                        color: theme.badgeFill
                        border.width: 1
                        border.color: theme.badgeRim

                        Text {
                            anchors.centerIn: parent
                            text: "󰂚"
                            color: theme.alpha(theme.accent, 0.82)
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 18
                        }
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "All clear"
                        color: theme.textPrimary
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "No unread notifications"
                        color: theme.textSecondary
                        font.pixelSize: 10
                        textFormat: Text.PlainText
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    width: 3
                    radius: 2
                    color: theme.alpha(theme.accent, 0.40)
                    visible: historyList.contentHeight > historyList.height
                    height: Math.max(24, historyList.height * historyList.height / historyList.contentHeight)
                    y: historyList.contentHeight <= historyList.height
                        ? 0
                        : (historyList.contentY / (historyList.contentHeight - historyList.height))
                            * (historyList.height - height)
                }
            }
        }
    }
}
