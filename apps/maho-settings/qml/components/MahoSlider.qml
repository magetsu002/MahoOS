import QtQuick
import QtQuick.Controls

Slider {
    id: root

    property color accent: "#d0bcff"
    property color foreground: "#f3eef8"
    property bool backendOwned: false
    property real backendValue: from
    signal valueRequested(real value)

    implicitHeight: 28

    function syncBackendValue() {
        if (!root.backendOwned || root.pressed)
            return
        root.value = Math.max(root.from, Math.min(root.to, root.backendValue))
    }

    Component.onCompleted: root.syncBackendValue()
    onBackendValueChanged: root.syncBackendValue()
    onPressedChanged: {
        if (!root.backendOwned || root.pressed)
            return
        const candidate = root.value
        root.value = Math.max(root.from, Math.min(root.to, root.backendValue))
        root.valueRequested(candidate)
    }

    background: Rectangle {
        x: root.leftPadding
        y: root.topPadding + root.availableHeight / 2 - height / 2
        width: root.availableWidth
        height: 5
        radius: 3
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.11)

        Rectangle {
            width: root.visualPosition * parent.width
            height: parent.height
            radius: parent.radius
            color: root.accent
        }
    }

    handle: Rectangle {
        x: root.leftPadding + root.visualPosition * (root.availableWidth - width)
        y: root.topPadding + root.availableHeight / 2 - height / 2
        width: 17
        height: 17
        radius: 9
        color: root.accent
        border.width: 2
        border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.20)
    }
}
