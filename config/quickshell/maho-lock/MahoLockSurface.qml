import QtQuick
import Quickshell.Wayland

WlSessionLockSurface {
    id: root

    required property var theme
    required property var state
    required property var auth

    color: theme.background

    MahoLockViewV6 {
        anchors.fill: parent
        theme: root.theme
        lockState: root.state
        auth: root.auth
        previewMode: false
    }
}
