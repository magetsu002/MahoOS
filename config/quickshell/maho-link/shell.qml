//@ pragma ShellId maho-link

import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoLinkTheme { id: theme }
    MahoLinkState { id: wifi }

    property bool presented: true
    property bool overlayOpen: false

    readonly property string stateBase: {
        const configured = Quickshell.env("XDG_STATE_HOME")
        return configured && String(configured) !== ""
            ? String(configured)
            : Quickshell.env("HOME") + "/.local/state"
    }
    readonly property string dockEdge:
        dockState.edge === "left" || dockState.edge === "right"
            || dockState.edge === "top" || dockState.edge === "bottom"
            ? dockState.edge : "top"
    readonly property real dockPosition: {
        const numeric = Number(dockState.position)
        if (!isFinite(numeric))
            return 0.5
        return Math.max(0.08, Math.min(0.92, numeric))
    }
    readonly property bool dockOccupiesRightSide:
        dockEdge === "right"
            || ((dockEdge === "top" || dockEdge === "bottom") && dockPosition > 0.5)

    function surfaceX(containerWidth, surfaceWidth, margin) {
        // Place transient surfaces on the opposite screen side from Maho Edge's
        // actual location, not merely its orientation. A top/bottom Edge can be
        // dragged along the edge, so its persisted position must participate.
        if (dockOccupiesRightSide)
            return margin
        return Math.max(margin, containerWidth - surfaceWidth - margin)
    }

    FileView {
        path: root.stateBase + "/quickshell/by-shell/maho-shell/dock.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: reload()

        JsonAdapter {
            id: dockState
            property int version: 1
            property string edge: "top"
            property real position: 0.5
        }
    }

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
            x: root.surfaceX(overlay.width, width, 24)
            y: 20
            theme: theme
            wifi: wifi
            availableHeight: overlay.height
            shown: root.overlayOpen
            onCloseRequested: root.closeOverlay()
        }
    }
}
