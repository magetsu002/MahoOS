//@ pragma ShellId maho-themes

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "."

ShellRoot {
    id: root

    property var filterBarItem: null

    property string onlineSearchScript: {
        let path = Qt.resolvedUrl("scripts/online_search.sh").toString()
        return path.startsWith("file://")
            ? decodeURIComponent(path.substring(7))
            : path
    }

    function invalidateOnlineSearch() {
        Quickshell.execDetached([
            "bash",
            root.onlineSearchScript,
            "--invalidate"
        ])
    }

    function hideLegacyBranding() {
        for (let i = 0; i < picker.children.length; i++) {
            const child = picker.children[i]
            if (Number(child.z) === 30 && Math.abs(Number(child.height) - picker.s(38)) < 2) {
                child.visible = false
            }
        }
    }

    function discoverFilterBar() {
        for (let i = 0; i < picker.children.length; i++) {
            const child = picker.children[i]
            if (Number(child.z) === 20 && Math.abs(Number(child.height) - picker.s(56)) < 2) {
                root.filterBarItem = child
                break
            }
        }
        root.updateFilterBarPosition()
    }

    function updateFilterBarPosition() {
        if (!root.filterBarItem)
            return
        root.filterBarItem.anchors.bottomMargin = picker.isReady
            ? picker.s(-10)
            : picker.s(-100)
    }

    function disableLegacyEscapeShortcut() {
        const objects = picker.data || []
        for (let i = 0; i < objects.length; i++) {
            const object = objects[i]
            try {
                if (!object || object.sequence === undefined)
                    continue
                const sequence = String(object.sequence).toLowerCase()
                if (sequence === "escape" || sequence === "esc")
                    object.enabled = false
            } catch (error) {
                // Non-Shortcut objects simply do not expose these properties.
            }
        }
    }

    function polishPickerRuntime() {
        root.hideLegacyBranding()
        root.discoverFilterBar()
        root.disableLegacyEscapeShortcut()
        picker.forceActiveFocus()
    }

    PanelWindow {
        id: overlay

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        visible: true
        color: "transparent"
        aboveWindows: true
        focusable: true
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        mask: Region { item: pickerSurface }

        Shortcut {
            sequence: "Escape"
            context: Qt.ApplicationShortcut
            enabled: !picker.isApplying
            onActivated: Qt.quit()
        }

        Shortcut {
            sequence: "Return"
            context: Qt.ApplicationShortcut
            enabled: picker.currentFilter === "Search"
                     && !picker.isApplying
                     && !picker.isSearchingOnline
            onActivated: {
                const normalized = String(picker.searchQuery || "").trim()
                if (normalized !== "") {
                    picker.triggerOnlineSearch(normalized)
                }
            }
        }

        Item {
            id: pickerSurface
            width: Math.round(overlay.width * 0.94)
            height: Math.round(overlay.height * 0.30)
            anchors.centerIn: parent

            WallpaperPicker {
                id: picker
                anchors.fill: parent
                focus: true

                onSearchQueryChanged: root.invalidateOnlineSearch()

                Component.onCompleted: Qt.callLater(root.polishPickerRuntime)
            }

            Connections {
                target: picker
                function onIsReadyChanged() {
                    Qt.callLater(root.updateFilterBarPosition)
                }
            }

            Rectangle {
                id: searchStatus
                z: 1000
                visible: picker.currentFilter === "Search"
                anchors.right: parent.right
                anchors.rightMargin: 18
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 14
                width: statusColumn.implicitWidth + 28
                height: statusColumn.implicitHeight + 18
                radius: 10
                color: "#B51B1B1B"
                border.width: 1
                border.color: "#55FFFFFF"

                Column {
                    id: statusColumn
                    anchors.centerIn: parent
                    spacing: 3

                    Text {
                        text: {
                            if (picker.isSearchingOnline)
                                return "SEARCHING ONLINE"
                            if (picker.onlineSearchError !== "")
                                return "ONLINE SEARCH FAILED"
                            if (picker.isOnlineSearch)
                                return picker.visibleItemCount > 0
                                    ? "ONLINE RESULTS"
                                    : "NO ONLINE RESULTS"
                            return picker.visibleItemCount > 0
                                ? "LOCAL RESULTS"
                                : "NO LOCAL RESULTS"
                        }
                        color: "white"
                        font.bold: true
                        font.pixelSize: 12
                        font.family: "JetBrains Mono"
                    }

                    Text {
                        text: "Type to search locally • Press Enter to search online"
                        color: "#D9FFFFFF"
                        font.pixelSize: 11
                        font.family: "JetBrains Mono"
                    }
                }
            }
        }
    }
}
