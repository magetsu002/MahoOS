import QtQuick

Item {
    id: root

    required property var theme
    required property var identityResolver
    property var notification: null
    property var entry: null
    property int iconSize: 26
    property int cornerRadius: 8
    property color backgroundColor: theme.alpha(theme.primary, 0.13)
    property color foregroundColor: theme.primary
    property int candidateIndex: 0
    readonly property var resolution: notification
        ? identityResolver.resolveNotification(notification)
        : identityResolver.resolveHistory(entry)
    readonly property var candidates: resolution.candidates || []
    readonly property string currentSource: candidateIndex < candidates.length
        ? candidates[candidateIndex].source : ""
    readonly property string currentRoute: candidateIndex < candidates.length
        ? candidates[candidateIndex].route : "fallback"
    readonly property string appName: notification
        ? String(notification.appName || "Notification")
        : String((entry && entry.appName) || "Notification")

    width: iconSize
    height: iconSize

    onResolutionChanged: candidateIndex = 0

    Rectangle {
        anchors.fill: parent
        radius: root.cornerRadius
        color: root.backgroundColor
        visible: appImage.status !== Image.Ready

        Text {
            anchors.centerIn: parent
            text: root.appName.slice(0, 1).toUpperCase()
            color: root.foregroundColor
            font.pixelSize: 12
            font.weight: Font.DemiBold
            textFormat: Text.PlainText
        }
    }

    Image {
        id: appImage
        anchors.fill: parent
        source: root.currentSource
        sourceSize.width: root.iconSize
        sourceSize.height: root.iconSize
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        cache: true

        onStatusChanged: {
            if (status === Image.Error && root.candidateIndex + 1 < root.candidates.length)
                root.candidateIndex += 1
        }
    }
}
