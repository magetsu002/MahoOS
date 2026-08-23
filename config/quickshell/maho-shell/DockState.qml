import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: dockState

    property string edge: normalizeEdge(adapter.edge)
    property real position: clampPosition(adapter.position)

    function normalizeEdge(value) {
        if (value === "top" || value === "bottom" || value === "left" || value === "right")
            return value
        return "top"
    }

    function clampPosition(value) {
        const numeric = Number(value)
        if (!isFinite(numeric))
            return 0.5
        return Math.max(0.08, Math.min(0.92, numeric))
    }

    function setDock(nextEdge, nextPosition) {
        const cleanEdge = normalizeEdge(nextEdge)
        const cleanPosition = clampPosition(nextPosition)

        if (adapter.edge !== cleanEdge)
            adapter.edge = cleanEdge
        if (Math.abs(adapter.position - cleanPosition) > 0.0001)
            adapter.position = cleanPosition
    }

    FileView {
        id: stateFile
        path: Quickshell.statePath("dock.json")
        watchChanges: true
        atomicWrites: true
        onFileChanged: reload()
        onAdapterUpdated: writeAdapter()

        JsonAdapter {
            id: adapter
            property int version: 1
            property string edge: "top"
            property real position: 0.5
        }
    }

    Component.onCompleted: {
        const cleanEdge = normalizeEdge(adapter.edge)
        const cleanPosition = clampPosition(adapter.position)

        if (adapter.edge !== cleanEdge || Math.abs(adapter.position - cleanPosition) > 0.0001)
            setDock(cleanEdge, cleanPosition)
    }
}
