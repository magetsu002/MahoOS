import QtQuick

Item {
    id: root
    required property var chrome
    property int strength: 0
    property color barColor: chrome.accent

    readonly property int activeBars: strength >= 80 ? 4 : strength >= 58 ? 3 : strength >= 32 ? 2 : 1

    width: 28
    height: 23

    Repeater {
        model: 4

        Rectangle {
            width: 4
            height: 5 + index * 4
            x: index * 6
            y: root.height - height
            radius: 2
            color: index < root.activeBars
                ? root.barColor
                : root.chrome.theme.alpha(root.chrome.textSecondary, 0.20)
        }
    }
}
