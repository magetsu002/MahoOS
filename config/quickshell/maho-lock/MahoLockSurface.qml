import QtQuick
import Quickshell.Wayland

WlSessionLockSurface {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    required property bool secure

    readonly property bool surfaceReady:
        secure && visible && width > 0 && height > 0

    color: theme.background

    onSurfaceReadyChanged: console.info(
        "maho-lock lifecycle: secure surface ready=" + surfaceReady
        + "; secure=" + secure
        + "; visible=" + visible
        + "; size=" + Math.round(width) + "x" + Math.round(height)
    )

    MahoLockViewV7 {
        anchors.fill: parent
        theme: root.theme
        lockState: root.lockState
        auth: root.auth
        surfaceReady: root.surfaceReady
        previewMode: false
    }
}
