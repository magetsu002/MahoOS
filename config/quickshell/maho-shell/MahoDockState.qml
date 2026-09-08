import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root

    readonly property int maximumPins: 24
    property var pins: []
    property bool seeded: false

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
        root.pins = clean.slice(0)
        persist()
        if (userChange)
            root.pinsChangedByUser()
    }

    function hydrate(text) {
        if (!text || String(text).trim().length === 0)
            return
        try {
            const payload = JSON.parse(String(text))
            root.pins = sanitize(payload.pins)
            root.seeded = Boolean(payload.seeded)
        } catch (error) {
            console.warn("Maho Dock state load failed:", error)
        }
    }

    function persist() {
        stateFile.setText(JSON.stringify({
            "version": 1,
            "seeded": root.seeded,
            "pins": sanitize(root.pins)
        }, null, 4) + "\n")
    }

    function seedPins(ids) {
        if (root.seeded)
            return
        root.pins = sanitize(ids)
        root.seeded = true
        persist()
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
        blockWrites: true
        watchChanges: true
        atomicWrites: true
        onFileChanged: reload()
        onTextChanged: root.hydrate(text())
    }

    Component.onCompleted: root.hydrate(stateFile.text())
}
