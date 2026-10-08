import QtQuick
import QtQuick.Controls

Slider {
    id: root

    property color accent: "#d0bcff"
    property color foreground: "#f3eef8"
    property bool backendOwned: false
    property real backendValue: from
    property bool busy: false
    property bool optimisticActive: false
    property real optimisticValue: from
    signal valueRequested(real value)

    implicitHeight: 28

    function valuesMatch(a, b) {
        const tolerance = root.stepSize > 0 ? root.stepSize / 2 : 0.0005
        return Math.abs(Number(a) - Number(b)) <= tolerance
    }

    function syncBackendValue() {
        if (!root.backendOwned || root.pressed)
            return
        if (root.optimisticActive) {
            if (root.valuesMatch(root.backendValue, root.optimisticValue)) {
                root.optimisticActive = false
                optimisticFallback.stop()
            } else {
                return
            }
        }
        root.value = Math.max(root.from, Math.min(root.to, root.backendValue))
    }

    function rollbackOptimisticValue() {
        root.optimisticActive = false
        optimisticFallback.stop()
        root.value = Math.max(root.from, Math.min(root.to, root.backendValue))
    }

    Component.onCompleted: root.syncBackendValue()
    onBackendValueChanged: root.syncBackendValue()
    onBusyChanged: {
        if (!root.busy && root.optimisticActive) {
            Qt.callLater(function() {
                if (!root.optimisticActive)
                    return
                if (root.valuesMatch(root.backendValue, root.optimisticValue))
                    root.syncBackendValue()
                else
                    root.rollbackOptimisticValue()
            })
        }
    }

    onPressedChanged: {
        if (!root.backendOwned || root.pressed)
            return
        const candidate = root.value
        if (root.busy) {
            root.rollbackOptimisticValue()
            return
        }
        root.optimisticValue = candidate
        root.optimisticActive = true
        optimisticFallback.restart()
        root.valueRequested(candidate)
    }

    Timer {
        id: optimisticFallback
        interval: 3000
        repeat: false
        onTriggered: root.rollbackOptimisticValue()
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
