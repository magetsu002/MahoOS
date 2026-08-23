import QtQuick

Item {
    id: root

    required property var theme
    required property var notificationModel

    width: 324
    height: stack.implicitHeight

    Column {
        id: stack

        width: parent.width
        spacing: 9

        Repeater {
            model: root.notificationModel.visibleNotifications

            NotificationCard {
                required property var modelData

                width: stack.width
                theme: root.theme
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
