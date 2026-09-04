import QtQuick
import Quickshell.Wayland

WlSessionLockSurface {
    id: root

    required property var theme
    required property var state
    required property var auth

    // Keep the secure session-lock surface opaque. All wallpaper treatment is
    // rendered inside MahoLockView; the live desktop is never exposed through
    // transparency.
    color: theme.background

    MahoLockView {
        anchors.fill: parent
        theme: root.theme
        state: root.state
        auth: root.auth
        previewMode: false
    }
}
