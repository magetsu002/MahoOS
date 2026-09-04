import QtQuick
import Quickshell.Wayland

WlSessionLockSurface {
    id: root

    required property var theme
    required property var state
    required property var auth

    // Secure session-lock surface remains opaque. The chosen lock wallpaper and
    // all material are rendered inside the shared production view.
    color: theme.background

    MahoLockViewV5 {
        anchors.fill: parent
        theme: root.theme
        lockState: root.state
        auth: root.auth
        previewMode: false
    }
}
