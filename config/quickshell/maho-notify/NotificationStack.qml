import QtQuick

Item {
    id: root

    required property var theme
    required property var notificationModel
    required property var historyModel
    required property var identityResolver

    width: 324
    height: stack.implicitHeight

    Column {
        id: stack

        width: parent.width
        spacing: 9

        Repeater {
            model: root.notificationModel.replayEntries

            HistoryReplayCard {
                required property var modelData

                width: stack.width
                theme: root.theme
                identityResolver: root.identityResolver
                entry: modelData.entry
                onDismissRequested: root.notificationModel.dismissReplay(modelData.token)
                onActivated: {
                    if (root.historyModel.activateEntry(String(modelData.entry.id)))
                        root.notificationModel.dismissReplay(modelData.token)
                }
            }
        }

        Repeater {
            model: root.notificationModel.visibleNotifications

            NotificationCard {
                required property var modelData

                width: stack.width
                theme: root.theme
                identityResolver: root.identityResolver
                notification: modelData.notification
                groupCount: modelData.groupCount
                onDismissRequested: root.notificationModel.dismissGroup(modelData)
                onExpireRequested: root.notificationModel.expireGroup(modelData)
            }
        }

        add: Transition {
            NumberAnimation { properties: "opacity,y"; from: 0; duration: 180 }
        }

        move: Transition {
            NumberAnimation { properties: "y"; duration: 180; easing.type: Easing.OutCubic }
        }
    }
}
