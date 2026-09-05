import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    property bool active: true

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    visible: root.active
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    aboveWindows: true
    focusable: false
    mask: Region {}

    // This surface exists only to carry compositor blur. Keep it below the
    // interactive Overlay plane and keep its alpha stable so Hyprland never
    // toggles blur halfway through Link's entrance animation.
    WlrLayershell.namespace: "maho-link-backdrop"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.008)
    }
}
