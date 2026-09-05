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

    WlrLayershell.namespace: "maho-power-backdrop"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.008)
    }
}
