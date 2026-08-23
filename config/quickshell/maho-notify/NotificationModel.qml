import QtQuick

QtObject {
    id: model

    readonly property int maxVisible: 3
    property var visibleNotifications: []
    property var queuedNotifications: []
    readonly property int visibleCount: visibleNotifications.length
    readonly property int queuedCount: queuedNotifications.length

    function contains(notification) {
        return visibleNotifications.indexOf(notification) >= 0
            || queuedNotifications.indexOf(notification) >= 0
    }

    function enqueue(notification) {
        if (!notification || contains(notification))
            return

        notification.closed.connect(function(reason) {
            model.remove(notification)
        })

        if (visibleNotifications.length < maxVisible) {
            const nextVisible = visibleNotifications.slice()
            nextVisible.unshift(notification)
            visibleNotifications = nextVisible
        } else {
            const nextQueue = queuedNotifications.slice()
            nextQueue.push(notification)
            queuedNotifications = nextQueue
        }
    }

    function remove(notification) {
        let nextVisible = visibleNotifications.slice()
        let nextQueue = queuedNotifications.slice()
        const visibleIndex = nextVisible.indexOf(notification)
        const queueIndex = nextQueue.indexOf(notification)

        if (visibleIndex >= 0)
            nextVisible.splice(visibleIndex, 1)
        if (queueIndex >= 0)
            nextQueue.splice(queueIndex, 1)

        while (nextVisible.length < maxVisible && nextQueue.length > 0)
            nextVisible.push(nextQueue.shift())

        visibleNotifications = nextVisible
        queuedNotifications = nextQueue
    }

    function dismiss(notification) {
        if (!notification)
            return false
        notification.dismiss()
        return true
    }

    function dismissFirst() {
        if (visibleNotifications.length === 0)
            return false
        return dismiss(visibleNotifications[0])
    }

    function invokeFirstAction() {
        if (visibleNotifications.length === 0)
            return false

        const notification = visibleNotifications[0]
        if (!notification.actions || notification.actions.length === 0)
            return false

        notification.actions[0].invoke()
        return true
    }
}
