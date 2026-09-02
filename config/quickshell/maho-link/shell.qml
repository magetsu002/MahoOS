//@ pragma ShellId maho-link

import QtQuick
import Quickshell
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoLinkTheme { id: theme }
    MahoLinkState { id: wifi }

    property bool presented: true
    property bool overlayOpen: false

    function showOverlay() {
        closeTimer.stop()
        presented = true
        overlayOpen = true
        linkSurface.shown = true
        linkSurface.forceActiveFocus()
    }

    function closeOverlay() {
        if (!overlayOpen)
            return
        overlayOpen = false
        linkSurface.shown = false
        closeTimer.restart()
    }

    Component.onCompleted: openDelay.restart()

    Timer {
        id: openDelay
        interval: 12
        onTriggered: root.showOverlay()
    }

    Timer {
        id: closeTimer
        interval: 175
        onTriggered: {
            root.presented = false
            Qt.quit()
        }
    }

    PanelWindow {
        id: overlay

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        color: "transparent"
        aboveWindows: true
        focusable: root.overlayOpen
        exclusionMode: ExclusionMode.Ignore
        visible: root.presented

        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "maho-link"

        Rectangle {
            anchors.fill: parent
            color: Qt.rgba(0, 0, 0, root.overlayOpen ? 0.16 : 0)
            Behavior on color { ColorAnimation { duration: 170 } }
        }

        MouseArea {
            anchors.fill: parent
            enabled: root.overlayOpen
            onClicked: root.closeOverlay()
        }

        MahoLink {
            id: linkSurface
            x: Math.max(18, overlay.width - width - 24)
            y: 20
            theme: theme
            wifi: wifi
            availableHeight: overlay.height
            shown: root.overlayOpen
            onCloseRequested: root.closeOverlay()
        }
    }
}
