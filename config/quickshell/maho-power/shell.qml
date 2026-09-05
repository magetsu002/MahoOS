//@ pragma ShellId maho-power

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoTheme { id: theme }
    PowerBackdrop { id: backdrop; active: root.presented }

    // `presented` now owns only the compositor carrier lifecycle. It starts
    // true so the stable blur plane is committed before the foreground moves.
    // `panelVisible` owns the animated UI. Separating them prevents Hyprland's
    // blur onset from racing the translucent panel scale/opacity animation and
    // looking like a duplicate layer underneath it.
    property bool presented: true
    property bool panelVisible: false
    property bool closing: false

    function closeOverlay() {
        if (closing)
            return
        closing = true
        presented = false
        panelVisible = false
        closeTimer.restart()
    }

    function focusPanel() {
        // A second key press during the short close animation restores the same
        // process coherently instead of focusing a half-dismissed surface.
        if (closing) {
            closeTimer.stop()
            closing = false
            presented = true
            panelVisible = true
        }
        powerView.forceActiveFocus()
    }

    function executeAction(action) {
        closing = true
        presented = false
        panelVisible = false
        Quickshell.execDetached([
            Quickshell.env("HOME") + "/.local/bin/maho-power",
            "action",
            action
        ])
        actionQuitTimer.restart()
    }

    // Match the accepted Launcher sequencing: the blur carrier is already
    // mapped when the config is instantiated; reveal foreground content on the
    // next Qt turn instead of creating blur and motion in the same frame.
    Component.onCompleted: Qt.callLater(function() {
        root.panelVisible = true
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
            opacity: root.panelVisible ? 1 : 0

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
            opacity: root.panelVisible ? 1 : 0
            scale: root.panelVisible ? 1 : 0.965

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
