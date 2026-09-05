//@ pragma ShellId maho-power

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoTheme { id: theme }
    PowerBackdrop { id: backdrop }

    property bool presented: false
    property bool closing: false

    function closeOverlay() {
        if (closing)
            return
        closing = true
        presented = false
        closeTimer.restart()
    }

    function focusPanel() {
        powerView.forceActiveFocus()
    }

    function executeAction(action) {
        presented = false
        Quickshell.execDetached([
            Quickshell.env("HOME") + "/.local/bin/maho-power",
            "action",
            action
        ])
        actionQuitTimer.restart()
    }

    Component.onCompleted: presentTimer.restart()

    Timer {
        id: presentTimer
        interval: 1
        onTriggered: {
            root.presented = true
            powerView.forceActiveFocus()
        }
    }

    Timer {
        id: closeTimer
        interval: 150
        onTriggered: Qt.quit()
    }

    Timer {
        id: actionQuitTimer
        interval: 100
        onTriggered: Qt.quit()
    }

    PanelWindow {
        id: overlay

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        aboveWindows: true
        focusable: true

        WlrLayershell.namespace: "maho-power"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        Rectangle {
            anchors.fill: parent
            color: theme.alpha(theme.background, 0.18)
            opacity: root.presented ? 1 : 0

            Behavior on opacity {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }
        }

        Rectangle {
            id: depthShadow
            anchors.centerIn: parent
            width: Math.min(900, Math.max(720, overlay.width * 0.54))
            height: Math.min(590, Math.max(500, overlay.height * 0.56))
            radius: 40
            color: Qt.rgba(0, 0, 0, 0.18)
            opacity: root.presented ? 1 : 0
            scale: root.presented ? 1 : 0.965

            Behavior on opacity { NumberAnimation { duration: 155 } }
            Behavior on scale { NumberAnimation { duration: 185; easing.type: Easing.OutCubic } }
        }

        MahoPowerView {
            id: powerView
            anchors.centerIn: parent
            width: Math.min(860, Math.max(700, overlay.width * 0.52))
            height: Math.min(570, Math.max(490, overlay.height * 0.55))
            theme: theme
            compact: false
            keyboardNavigation: true
            closeButtonVisible: true
            opacity: root.presented ? 1 : 0
            scale: root.presented ? 1 : 0.965

            Behavior on opacity {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }

            Behavior on scale {
                NumberAnimation { duration: 185; easing.type: Easing.OutCubic }
            }

            onCloseRequested: root.closeOverlay()
            onActionRequested: function(action) { root.executeAction(action) }
        }
    }

    IpcHandler {
        target: "power"

        function close(): bool {
            root.closeOverlay()
            return true
        }

        function focus(): bool {
            root.focusPanel()
            return true
        }
    }
}
