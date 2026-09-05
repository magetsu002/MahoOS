import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root

    readonly property int maximumPins: 24
    property var pins: sanitize(adapter.pins)
    property bool seeded: Boolean(adapter.seeded)

    signal pinsChangedByUser()

    function sanitize(value) {
        if (!Array.isArray(value))
            return []

        const output = []
        const seen = ({})
        for (let index = 0; index < value.length && output.length < maximumPins; ++index) {
            const id = String(value[index] || "").trim()
            if (id.length === 0 || seen[id])
                continue
            seen[id] = true
            output.push(id)
        }
        return output
    }

    function publish(nextPins, userChange) {
        const clean = sanitize(nextPins)
        adapter.pins = clean
        root.pins = clean.slice(0)
        if (userChange)
            root.pinsChangedByUser()
    }

    function seedPins(ids) {
        if (root.seeded)
            return
        publish(ids, false)
        adapter.seeded = true
        root.seeded = true
    }

    function contains(id) {
        return root.pins.indexOf(String(id || "")) >= 0
    }

    function pin(id) {
        const value = String(id || "").trim()
        if (value.length === 0 || contains(value) || root.pins.length >= maximumPins)
            return
        const next = root.pins.slice(0)
        next.push(value)
        publish(next, true)
    }

    function unpin(id) {
        const value = String(id || "")
        const next = root.pins.filter(function(entry) { return entry !== value })
        if (next.length !== root.pins.length)
            publish(next, true)
    }

    function movePin(fromIndex, toIndex) {
        if (fromIndex < 0 || fromIndex >= root.pins.length)
            return
        const bounded = Math.max(0, Math.min(root.pins.length - 1, toIndex))
        if (fromIndex === bounded)
            return
        const next = root.pins.slice(0)
        const moved = next.splice(fromIndex, 1)[0]
        next.splice(bounded, 0, moved)
        publish(next, true)
    }

    FileView {
        id: stateFile
        path: Quickshell.statePath("maho-dock.json")
        blockLoading: true
        watchChanges: true
        atomicWrites: true
        onFileChanged: reload()
        onAdapterUpdated: writeAdapter()

        JsonAdapter {
            id: adapter
            property int version: 1
            property bool seeded: false
            property var pins: []
        }
    }

    Component.onCompleted: {
        const clean = sanitize(adapter.pins)
        const serializedCurrent = JSON.stringify(Array.isArray(adapter.pins) ? adapter.pins : [])
        const serializedClean = JSON.stringify(clean)
        if (adapter.version !== 1)
            adapter.version = 1
        if (serializedCurrent !== serializedClean)
            adapter.pins = clean
        root.pins = clean.slice(0)
        root.seeded = Boolean(adapter.seeded)
    }
}
