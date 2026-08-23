import Quickshell
import Quickshell.Services.Notifications

Scope {
    id: service

    signal notificationReceived(var notification)

    NotificationServer {
        id: server

        keepOnReload: false
        persistenceSupported: true
        bodySupported: true
        bodyMarkupSupported: false
        bodyHyperlinksSupported: false
        bodyImagesSupported: false
        actionsSupported: true
        actionIconsSupported: false
        imageSupported: true
        inlineReplySupported: false

        onNotification: notification => {
            notification.tracked = true
            service.notificationReceived(notification)
        }
    }
}
