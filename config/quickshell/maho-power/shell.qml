//@ pragma ShellId maho-power

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoTheme { id: theme }
    PowerBackdrop { id: backdrop; active: root.backdropActive }

    // The compositor blur carrier must exist before the foreground panel starts
    // moving. If its mapping follows `presented`, Hyprland commits blur while the
    // translucent panel is already scaling in, which reads as a second/ghost
    // layer underneath the card. Keep the stable carrier mapped from process
    // startup, then unmap it immediately when dismissal begins.
    property bool backdropActive: true
    property bool presented: false
    property bool closing: false

    function closeOverlay() {
        if (closing)
            return
        closing = true
        backdropActive = false
        presented = false
        closeTimer.restart()
    }

    function focusPanel() {
        // A second key press during the short close animation should restore one
        // coherent surface rather than focus a half-dismissed instance.
        if (closing) {
            closeTimer.stop()
            closing = false
            backdropActive = true
            presented = true
        }
        powerView.forceActiveFocus()
    }

    function executeAction(action) {
        closing = true
        backdropActive = false
        presented = false
        Quickshell.execDetached([
            Quickshell.env("HOME") + "/.local/bin/maho-power",
            "action",
            action
        ])
        actionQuitTimer.restart()
    }

    // Match the accepted Launcher compositor sequencing: let the stable blur
    // plane be created first, then reveal the moving foreground on the next Qt
    // turn. This avoids blur-onset racing the scale/opacity animation.
    Component.onCompleted: Qt.callLater(function() {
        root.presented = true
        powerView.forceActiveFocus()
    })

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
            color: theme.alpha(theme.background, 0.055)
            opacity: root.presented ? 1 : 0

            Behavior on opacity {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }
        }

        MahoPowerView {
            id: powerView
            anchors.centerIn: parent
            width: Math.min(860, Math.max(760, overlay.width * 0.56))
            height: Math.min(570, Math.max(500, overlay.height * 0.57))
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
