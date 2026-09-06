//@ pragma ShellId maho-clipboard

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    ClipboardTheme { id: theme }
    ClipboardState { id: clipboard }

    property bool presented: true
    property bool overlayOpen: false
    readonly property string runtimeIdentity: Quickshell.env("MAHO_RUNTIME_IDENTITY")

    function showOverlay() {
        closeTimer.stop()
        presented = true
        overlayOpen = true
        clipboardSurface.shown = true
    }

    function closeOverlay() {
        if (!overlayOpen)
            return
        overlayOpen = false
        clipboardSurface.shown = false
        closeTimer.restart()
    }

    function toggleOverlay() {
        if (overlayOpen)
            closeOverlay()
        else
            showOverlay()
    }

    // The launcher uses this handler when a second SUPER+V arrives while this
    // instance already owns the clipboard lock. Keeping the toggle in-process
    // preserves the intentional closing animation instead of killing Quickshell.
    IpcHandler {
        target: "clipboard"

        function toggle(): void { root.toggleOverlay() }
        function open(): void { root.showOverlay() }
        function close(): void { root.closeOverlay() }
        function runtimeIdentity(): string { return root.runtimeIdentity }
        function retire(nextIdentity: string): bool {
            if (nextIdentity === root.runtimeIdentity)
                return false
            root.overlayOpen = false
            clipboardSurface.shown = false
            root.presented = false
            retireTimer.restart()
            return true
        }
    }

    Component.onCompleted: openDelay.restart()

    Timer {
        id: retireTimer
        interval: 1
        onTriggered: Qt.quit()
    }

    Timer {
        id: openDelay
        interval: 12
        onTriggered: root.showOverlay()
    }

    Timer {
        id: closeTimer
        // Keep the layer alive until the QML sheet has fully fallen below the
        // monitor. Hyprland animation is disabled for this namespace so only
        // the intentional sheet motion is visible.
        interval: 285
        onTriggered: {
            root.presented = false
            Qt.quit()
        }
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
        aboveWindows: true
        // Match the proven Maho Launcher model: the layer is keyboard-capable
        // for its whole lifetime instead of trying to turn focusability on only
        // after the Wayland surface already exists.
        focusable: true
        exclusionMode: ExclusionMode.Ignore
        visible: root.presented

        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "maho-clipboard"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        // Own the navigation at window scope as well as inside the search field.
        // This makes arrows/Enter reliable even if Qt moves item focus during
        // the opening transition, while leaving ordinary typing to TextInput.
        Shortcut {
            sequence: "Down"
            context: Qt.WindowShortcut
            enabled: root.overlayOpen
            onActivated: clipboardSurface.moveSelection(1)
        }

        Shortcut {
            sequence: "Up"
            context: Qt.WindowShortcut
            enabled: root.overlayOpen
            onActivated: clipboardSurface.moveSelection(-1)
        }

        Shortcut {
            sequence: "Return"
            context: Qt.WindowShortcut
            enabled: root.overlayOpen
            onActivated: clipboardSurface.activateSelection()
        }

        Shortcut {
            sequence: "Enter"
            context: Qt.WindowShortcut
            enabled: root.overlayOpen
            onActivated: clipboardSurface.activateSelection()
        }

        Shortcut {
            sequence: "Esc"
            context: Qt.WindowShortcut
            enabled: root.overlayOpen
            onActivated: root.closeOverlay()
        }

        // Keep surrounding windows readable and visually present. This alpha
        // stays below the clipboard blur rule's threshold, so Hyprland blurs
        // the sheet itself rather than producing a fake full-width blur band.
        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.overlayOpen ? 0.050 : 0)
            Behavior on color { ColorAnimation { duration: root.overlayOpen ? 300 : 170 } }
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.overlayOpen
            onClicked: root.closeOverlay()
        }

        ClipboardPanel {
            id: clipboardSurface
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            theme: theme
            clipboardState: clipboard
            shown: root.overlayOpen
            onCloseRequested: root.closeOverlay()
        }
    }
}
