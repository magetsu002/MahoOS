import QtQuick

Item {
    id: center

    required property var theme
    required property var historyModel
    required property real availableHeight

    signal closeRequested()

    width: 420
    height: Math.min(680, Math.max(320, availableHeight - 36))
    focus: true

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
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: 18
        color: theme.alpha(theme.surfaceHigh, 0.982)
        border.width: 1
        border.color: theme.alpha(theme.outline, 0.28)

        Column {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 10

            Row {
                width: parent.width
                height: 38
                spacing: 8

                Column {
                    width: parent.width - dndButton.width - closeButton.width - 16
                    spacing: 1

                    Text {
                        width: parent.width
                        text: "Maho Notify"
                        color: theme.foreground
                        font.pixelSize: 17
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }

                    Text {
                        width: parent.width
                        text: historyModel.unreadCount > 0
                            ? String(historyModel.unreadCount) + " unread · " + String(historyModel.retainedCount) + " retained"
                            : String(historyModel.retainedCount) + " retained"
                        color: theme.muted
                        font.pixelSize: 10
                        textFormat: Text.PlainText
                    }
                }

                Rectangle {
                    id: dndButton
                    width: 58
                    height: 30
                    radius: 10
                    color: historyModel.dndEnabled
                        ? theme.alpha(theme.primary, dndHover.hovered ? 0.24 : 0.17)
                        : theme.alpha(theme.foreground, dndHover.hovered ? 0.09 : 0.045)
                    border.width: 1
                    border.color: theme.alpha(historyModel.dndEnabled ? theme.primary : theme.outline, 0.28)

                    Text {
                        anchors.centerIn: parent
                        text: historyModel.dndEnabled ? "DND on" : "DND off"
                        color: historyModel.dndEnabled ? theme.primary : theme.muted
                        font.pixelSize: 10
                        font.weight: Font.Medium
                        textFormat: Text.PlainText
                    }

                    HoverHandler { id: dndHover }
                    TapHandler { onTapped: historyModel.toggleDnd() }
                }

                Rectangle {
                    id: closeButton
                    width: 30
                    height: 30
                    radius: 10
                    color: closeHover.hovered ? theme.alpha(theme.foreground, 0.09) : "transparent"

                    Text {
                        anchors.centerIn: parent
                        text: "×"
                        color: theme.muted
                        font.pixelSize: 18
                        textFormat: Text.PlainText
                    }

                    HoverHandler { id: closeHover }
                    TapHandler { onTapped: center.closeRequested() }
                }
            }

            Row {
                width: parent.width
                height: 28
                spacing: 7

                Repeater {
                    model: [
                        {"label": "Mark read", "action": "read"},
                        {"label": "Clear read", "action": "clearRead"},
                        {"label": "Clear all", "action": "clearAll"}
                    ]

                    Rectangle {
                        required property var modelData
                        width: actionText.implicitWidth + 20
                        height: 27
                        radius: 9
                        color: actionHover.hovered
                            ? theme.alpha(theme.primary, 0.14)
                            : theme.alpha(theme.foreground, 0.035)
                        border.width: 1
                        border.color: theme.alpha(theme.outline, 0.15)

                        Text {
                            id: actionText
                            anchors.centerIn: parent
                            text: modelData.label
                            color: theme.muted
                            font.pixelSize: 10
                            font.weight: Font.Medium
                            textFormat: Text.PlainText
                        }

                        HoverHandler { id: actionHover }
                        TapHandler {
                            onTapped: {
                                if (modelData.action === "read")
                                    historyModel.markAllRead()
                                else if (modelData.action === "clearRead")
                                    historyModel.clearRead()
                                else
                                    historyModel.clearHistory()
                            }
                        }
                    }
                }
            }

            Item {
                width: parent.width
                height: parent.height - 38 - 28 - 20

                ListView {
                    id: historyList
                    anchors.fill: parent
                    clip: true
                    spacing: 7
                    reuseItems: true
                    cacheBuffer: 480
                    boundsBehavior: Flickable.StopAtBounds
                    model: historyModel.groupedEntries

                    delegate: HistoryRow {
                        required property var modelData
                        width: historyList.width
                        theme: center.theme
                        entry: modelData
                    }
                }

                Text {
                    anchors.centerIn: parent
                    visible: historyModel.retainedCount === 0
                    text: "Quiet here"
                    color: theme.alpha(theme.muted, 0.72)
                    font.pixelSize: 13
                    textFormat: Text.PlainText
                }

                Rectangle {
                    anchors.right: parent.right
                    width: 3
                    radius: 2
                    color: theme.alpha(theme.primary, 0.32)
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
