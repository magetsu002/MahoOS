import QtQuick
import Quickshell.Services.Notifications

QtObject {
    id: model

    readonly property int maxVisible: 3
    readonly property int maxQueued: 100
    readonly property int groupingWindowMs: 6000
    property var visibleNotifications: []
    property var queuedNotifications: []
    property var supersededNotifications: ({})
    property int suppressedPopupCount: 0
    property int droppedPopupCount: 0
    readonly property int visibleCount: visibleNotifications.length
    readonly property int queuedCount: queuedNotifications.length
    readonly property int livePopupCount: visibleCount + queuedCount

    function appKey(notification) {
        return String(notification.desktopEntry || notification.appName || "notification")
            .slice(0, 192)
            .toLowerCase()
    }

    function makeGroup(notification) {
        return {
            "notification": notification,
            "appKey": appKey(notification),
            "groupCount": 1,
            "lastAt": Date.now(),
            "critical": notification.urgency === NotificationUrgency.Critical
        }
    }

    function contains(notification) {
        const lists = [visibleNotifications, queuedNotifications]
        for (let listIndex = 0; listIndex < lists.length; ++listIndex) {
            for (let index = 0; index < lists[listIndex].length; ++index) {
                if (lists[listIndex][index].notification === notification)
                    return true
            }
        }
        return false
    }

    function connectLifetime(notification) {
        notification.closed.connect(function(reason) {
            model.handleClosed(notification)
        })
    }

    function findGroup(source, key, now) {
        for (let index = 0; index < source.length; ++index) {
            const group = source[index]
            if (!group.critical && group.appKey === key && now - group.lastAt <= groupingWindowMs)
                return index
        }
        return -1
    }

    function coalesce(sourceName, index, notification, now) {
        const source = sourceName === "visible"
            ? visibleNotifications.slice()
            : queuedNotifications.slice()
        const previous = source[index]
        const previousNotification = previous.notification
        const nextSuperseded = Object.assign({}, supersededNotifications)
        nextSuperseded[String(previousNotification.id)] = true
        supersededNotifications = nextSuperseded

        connectLifetime(notification)
        source[index] = Object.assign({}, previous, {
            "notification": notification,
            "groupCount": Number(previous.groupCount || 1) + 1,
            "lastAt": now
        })

        if (sourceName === "visible")
            visibleNotifications = source
        else
            queuedNotifications = source

        if (previousNotification.tracked)
            previousNotification.expire()
        return true
    }

    function enqueue(notification, dndEnabled) {
        if (!notification || contains(notification))
            return false

        const critical = notification.urgency === NotificationUrgency.Critical
        if (dndEnabled && !critical) {
            suppressedPopupCount += 1
            notification.expire()
            return false
        }

        const normal = notification.urgency === NotificationUrgency.Normal
        const now = Date.now()
        const key = appKey(notification)
        if (normal) {
            const visibleIndex = findGroup(visibleNotifications, key, now)
            if (visibleIndex >= 0)
                return coalesce("visible", visibleIndex, notification, now)

            const queueIndex = findGroup(queuedNotifications, key, now)
            if (queueIndex >= 0)
                return coalesce("queued", queueIndex, notification, now)
        }

        const group = makeGroup(notification)
        connectLifetime(notification)
        if (visibleNotifications.length < maxVisible) {
            const nextVisible = visibleNotifications.slice()
            nextVisible.unshift(group)
            visibleNotifications = nextVisible
            return true
        }

        let nextQueue = queuedNotifications.slice()
        if (nextQueue.length >= maxQueued) {
            let dropIndex = -1
            if (critical) {
                for (let index = nextQueue.length - 1; index >= 0; --index) {
                    if (!nextQueue[index].critical) {
                        dropIndex = index
                        break
                    }
                }
            }

            if (dropIndex < 0) {
                droppedPopupCount += 1
                notification.expire()
                return false
            }

            const dropped = nextQueue.splice(dropIndex, 1)[0]
            droppedPopupCount += 1
            if (dropped.notification.tracked)
                dropped.notification.expire()
        }

        nextQueue.push(group)
        queuedNotifications = nextQueue
        return true
    }

    function handleClosed(notification) {
        const key = String(notification.id)
        if (supersededNotifications[key]) {
            const nextSuperseded = Object.assign({}, supersededNotifications)
            delete nextSuperseded[key]
            supersededNotifications = nextSuperseded
            return
        }

        let nextVisible = visibleNotifications.slice()
        let nextQueue = queuedNotifications.slice()
        let found = false
        for (let index = nextVisible.length - 1; index >= 0; --index) {
            if (nextVisible[index].notification === notification) {
                nextVisible.splice(index, 1)
                found = true
            }
        }
        for (let index = nextQueue.length - 1; index >= 0; --index) {
            if (nextQueue[index].notification === notification) {
                nextQueue.splice(index, 1)
                found = true
            }
        }
        if (!found)
            return

        while (nextVisible.length < maxVisible && nextQueue.length > 0)
            nextVisible.push(nextQueue.shift())

        visibleNotifications = nextVisible
        queuedNotifications = nextQueue
    }

    function dismissGroup(group) {
        if (!group || !group.notification)
            return false
        group.notification.dismiss()
        return true
    }

    function expireGroup(group) {
        if (!group || !group.notification)
            return false
        group.notification.expire()
        return true
    }

    function dismissFirst() {
        if (visibleNotifications.length === 0)
            return false
        return dismissGroup(visibleNotifications[0])
    }

    function invokeFirstAction() {
        if (visibleNotifications.length === 0)
            return false

        const notification = visibleNotifications[0].notification
        if (!notification.actions || notification.actions.length === 0)
            return false

        notification.actions[0].invoke()
        return true
    }
}
