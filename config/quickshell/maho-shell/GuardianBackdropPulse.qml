import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    focusable: false
    mask: Region {}

    // Above wallpaper/background providers, below normal application windows.
    WlrLayershell.namespace: "maho-guardian-backdrop-pulse"
    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    property real pulseOpacity: 0.0

    function trigger() {
        pulse.stop()
        pulseOpacity = 0
        pulse.restart()
    }

    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: root.pulseOpacity
    }

    SequentialAnimation {
        id: pulse

        NumberAnimation {
            target: root
            property: "pulseOpacity"
            from: 0
            to: 0.46
            duration: 115
            easing.type: Easing.OutCubic
        }

        PauseAnimation { duration: 55 }

        NumberAnimation {
            target: root
            property: "pulseOpacity"
            to: 0
            duration: 285
            easing.type: Easing.OutCubic
        }
    }
}
