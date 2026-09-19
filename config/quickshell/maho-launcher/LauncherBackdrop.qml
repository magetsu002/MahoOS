import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    property bool active: false
    signal dismissRequested()

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    focusable: false
    visible: active
    mask: Region { item: root.active ? dimPlane : null }

    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "maho-launcher-catcher"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    Rectangle {
        id: dimPlane
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, root.active ? 0.14 : 0)
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.active
        onClicked: root.dismissRequested()
    }
}
