import QtQuick
import QtQuick.Controls

TextField {
    id: root

    property color surface: "#302b2b"
    property color foreground: "#f4eeee"
    property color muted: "#aaa3a3"
    property color accent: "#d8aaaa"
    property bool backendOwned: false
    property string backendText: ""
    property bool busy: false
    property bool optimisticActive: false
    property string optimisticText: ""
    signal textRequested(string text)

    function syncBackendText() {
        if (!root.backendOwned || root.activeFocus)
            return
        if (root.optimisticActive) {
            if (root.backendText === root.optimisticText) {
                root.optimisticActive = false
                optimisticFallback.stop()
            } else {
                return
            }
        }
        root.text = root.backendText
    }

    function rollbackOptimisticText() {
        root.optimisticActive = false
        optimisticFallback.stop()
        root.text = root.backendText
    }

    Component.onCompleted: root.syncBackendText()
    onBackendTextChanged: root.syncBackendText()
    onBusyChanged: {
        if (!root.busy && root.optimisticActive) {
            Qt.callLater(function() {
                if (!root.optimisticActive)
                    return
                if (root.backendText === root.optimisticText) {
                    root.optimisticActive = false
                    optimisticFallback.stop()
                } else {
                    root.rollbackOptimisticText()
                }
            })
        }
    }

    onEditingFinished: {
        if (!root.backendOwned)
            return
        const candidate = root.text
        if (candidate === root.backendText)
            return
        if (root.busy) {
            root.rollbackOptimisticText()
            return
        }
        root.optimisticText = candidate
        root.optimisticActive = true
        optimisticFallback.restart()
        root.textRequested(candidate)
    }

    Timer {
        id: optimisticFallback
        interval: 3000
        repeat: false
        onTriggered: root.rollbackOptimisticText()
    }

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 12
    topPadding: 0
    bottomPadding: 0
    selectByMouse: true
    color: root.foreground
    placeholderTextColor: Qt.rgba(root.muted.r, root.muted.g, root.muted.b, 0.72)
    font.pixelSize: 12

    background: Rectangle {
        radius: 11
        color: Qt.rgba(root.surface.r, root.surface.g, root.surface.b, root.hovered ? 0.78 : 0.62)
        border.width: 1
        border.color: root.activeFocus
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.32)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.075)
    }
}
