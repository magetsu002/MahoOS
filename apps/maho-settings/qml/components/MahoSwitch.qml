import QtQuick
import QtQuick.Controls

Switch {
    id: root

    property color accent: "#d0bcff"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property bool reducedMotion: false
    property bool busy: false

    // Backend state remains authoritative, but interaction feedback is
    // immediate. The optimistic visual is discarded as soon as verified
    // backend state arrives or the action finishes.
    property bool optimisticActive: false
    property bool optimisticValue: false
    readonly property bool visualChecked: optimisticActive ? optimisticValue : checked
    signal toggleRequested(bool value)

    checkable: false
    implicitWidth: 46
    implicitHeight: 26
    padding: 0
    opacity: root.enabled ? (root.down ? 0.86 : 1.0) : 0.46

    function requestToggle() {
        if (!root.enabled || root.busy)
            return
        root.optimisticValue = !root.checked
        root.optimisticActive = true
        optimisticFallback.restart()
        root.toggleRequested(root.optimisticValue)
    }

    onClicked: root.requestToggle()
    onCheckedChanged: {
        if (root.optimisticActive && root.checked === root.optimisticValue) {
            root.optimisticActive = false
            optimisticFallback.stop()
        }
    }
    onBusyChanged: {
        if (!root.busy && root.optimisticActive)
            Qt.callLater(function() { root.optimisticActive = false })
    }

    Timer {
        id: optimisticFallback
        interval: 2500
        repeat: false
        onTriggered: root.optimisticActive = false
    }

    indicator: Rectangle {
        implicitWidth: 44
        implicitHeight: 24
        radius: 12
        color: root.visualChecked
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.34)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
        border.width: 1
        border.color: root.visualChecked
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.48)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.085)

        Rectangle {
            width: 18
            height: 18
            radius: 9
            y: 3
            x: root.visualChecked ? parent.width - width - 3 : 3
            color: root.visualChecked ? root.accent : root.muted

            Behavior on x {
                NumberAnimation { duration: root.reducedMotion ? 0 : 120 }
            }
            Behavior on color {
                ColorAnimation { duration: root.reducedMotion ? 0 : 100 }
            }
        }

        Behavior on color {
            ColorAnimation { duration: root.reducedMotion ? 0 : 100 }
        }
    }

    contentItem: Item {}
}
