import QtQuick
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    property bool active: true
    visible: active

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    // This plane exists only to carry compositor blur. It must ignore Maho
    // Edge's DockReservation so the wallpaper/windows blur all the way to the
    // physical monitor edges, including behind the reserved strip.
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    aboveWindows: true
    focusable: false
    mask: Region {}

    // Keep the blur carrier below Maho Edge. Edge uses Overlay; Top still sits
    // above normal clients while allowing Edge to remain sharp and interactive.
    WlrLayershell.namespace: "maho-launcher-backdrop"
    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    // Do not animate this alpha through Hyprland's ignore-alpha threshold.
    // A tiny stable non-zero carrier is committed on the first frame; the
    // visible focus veil continues to animate in MahoLauncherWindow.qml.
    Rectangle {
        id: blurCarrier
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, 0.006)
    }
}
