import QtQuick
import Quickshell.Wayland

WlSessionLockSurface {
    id: root

    required property var theme
    required property var state
    required property var auth

    // Keep the secure session-lock surface opaque. All wallpaper treatment is
    // rendered inside the shared lock view; the live desktop is never exposed.
    color: theme.background

    MahoLockViewV2 {
        anchors.fill: parent
        theme: root.theme
        state: root.state
        auth: root.auth
        previewMode: false
    }
}
