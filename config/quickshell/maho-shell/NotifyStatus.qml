import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: status

    readonly property bool valid:
        statusFile.loaded
        && data.version === 1
        && Number(data.unread_count) >= 0
        && Number(data.unread_count) <= 500
        && Number(data.pid) > 0
    readonly property bool active: valid && Boolean(data.active)
    readonly property int unreadCount: active ? Math.floor(Number(data.unread_count)) : 0
    readonly property bool dndEnabled: active && Boolean(data.dnd)
    readonly property int processId: active ? Math.floor(Number(data.pid)) : 0
    readonly property string metadataPath: {
        const runtime = Quickshell.env("XDG_RUNTIME_DIR")
        return runtime !== "" ? runtime + "/maho/notify-status.json" : ""
    }

    FileView {
        id: statusFile
        path: status.metadataPath
        watchChanges: true
        blockLoading: false
        onFileChanged: reload()

        JsonAdapter {
            id: data
            property int version: 0
            property int unread_count: 0
            property bool dnd: false
            property bool active: false
            property int pid: 0
        }
    }
}
