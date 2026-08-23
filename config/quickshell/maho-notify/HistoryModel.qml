import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications

Scope {
    id: model

    readonly property int maxEntries: 500
    readonly property int maxAgeMs: 7 * 24 * 60 * 60 * 1000
    readonly property int groupWindowMs: 2 * 60 * 1000
    property var entries: []
    property bool dndEnabled: false
    property bool loaded: false
    property bool dirtyBeforeLoad: false
    property int serial: 0
    property var protocolEntries: ({})
    readonly property int retainedCount: entries.length
    readonly property int unreadCount: countUnread(entries)
    readonly property var groupedEntries: buildGroups(entries)

    function boundedText(value, maximum) {
        if (value === undefined || value === null)
            return ""
        return String(value).slice(0, maximum)
    }

    function safeIcon(notification) {
        const icon = boundedText(notification.appIcon, 512)
        if (icon.startsWith("data:") || icon.startsWith("image://"))
            return ""
        return icon
    }

    function appKey(notification) {
        const identity = notification.desktopEntry || notification.appName || "notification"
        return boundedText(identity, 192).toLowerCase()
    }

    function internalId() {
        serial += 1
        return String(Date.now()) + "-" + String(serial)
    }

    function closeReasonName(reason) {
        if (reason === NotificationCloseReason.Expired)
            return "expired"
        if (reason === NotificationCloseReason.CloseRequested)
            return "requested"
        return "dismissed"
    }

    function snapshot(notification) {
        const key = appKey(notification)
        return {
            "id": internalId(),
            "protocolId": Number(notification.id),
            "appKey": key,
            "appName": boundedText(notification.appName || "Notification", 192),
            "summary": boundedText(notification.summary || notification.appName || "Notification", 512),
            "body": boundedText(notification.body || "", 4096),
            "urgency": Number(notification.urgency),
            "timestamp": Date.now(),
            "read": false,
            "groupKey": key,
            "groupCount": 1,
            "replacementCount": 0,
            "closeReason": "live",
            "icon": safeIcon(notification),
            "transient": Boolean(notification.transient)
        }
    }

    function record(notification) {
        if (!notification)
            return

        const protocolKey = String(notification.id)
        if (protocolEntries[protocolKey] !== undefined) {
            applyReplacement(notification)
            return
        }

        const entry = snapshot(notification)
        const nextMap = Object.assign({}, protocolEntries)
        nextMap[protocolKey] = entry.id
        protocolEntries = nextMap

        const next = entries.slice()
        next.unshift(entry)
        entries = prune(next)
        scheduleSave()

        notification.appNameChanged.connect(function() { model.applyReplacement(notification) })
        notification.appIconChanged.connect(function() { model.applyReplacement(notification) })
        notification.summaryChanged.connect(function() { model.applyReplacement(notification) })
        notification.bodyChanged.connect(function() { model.applyReplacement(notification) })
        notification.urgencyChanged.connect(function() { model.applyReplacement(notification) })
        notification.closed.connect(function(reason) { model.markClosed(notification, reason) })
    }

    function entryIndexById(id) {
        for (let index = 0; index < entries.length; ++index) {
            if (entries[index].id === id)
                return index
        }
        return -1
    }

    function applyReplacement(notification) {
        const entryId = protocolEntries[String(notification.id)]
        const index = entryIndexById(entryId)
        if (index < 0)
            return

        const previous = entries[index]
        const updated = Object.assign({}, previous, {
            "appKey": appKey(notification),
            "appName": boundedText(notification.appName || "Notification", 192),
            "summary": boundedText(notification.summary || notification.appName || "Notification", 512),
            "body": boundedText(notification.body || "", 4096),
            "urgency": Number(notification.urgency),
            "timestamp": Date.now(),
            "read": false,
            "groupKey": appKey(notification),
            "replacementCount": Number(previous.replacementCount || 0) + 1,
            "icon": safeIcon(notification),
            "transient": Boolean(notification.transient)
        })
        const next = entries.slice()
        next.splice(index, 1)
        next.unshift(updated)
        entries = prune(next)
        scheduleSave()
    }

    function markClosed(notification, reason) {
        const protocolKey = String(notification.id)
        const entryId = protocolEntries[protocolKey]
        const index = entryIndexById(entryId)
        const nextMap = Object.assign({}, protocolEntries)
        delete nextMap[protocolKey]
        protocolEntries = nextMap

        if (index < 0)
            return
        const next = entries.slice()
        next[index] = Object.assign({}, next[index], {"closeReason": closeReasonName(reason)})
        entries = next
        scheduleSave()
    }

    function prune(source) {
        const cutoff = Date.now() - maxAgeMs
        const seen = ({})
        const retained = []

        for (let index = 0; index < source.length && retained.length < maxEntries; ++index) {
            const entry = source[index]
            if (!entry || Number(entry.timestamp) < cutoff || seen[entry.id])
                continue
            seen[entry.id] = true
            retained.push(entry)
        }
        return retained
    }

    function persistentEntries() {
        return prune(entries).filter(function(entry) { return !entry.transient }).map(function(entry) {
            const copy = Object.assign({}, entry)
            delete copy.transient
            return copy
        })
    }

    function scheduleSave() {
        if (!loaded) {
            dirtyBeforeLoad = true
            return
        }
        saveDelay.restart()
    }

    function saveNow() {
        if (!persistence.running)
            return
        persistence.write(JSON.stringify({
            "op": "save",
            "state": {"version": 2, "dnd": dndEnabled, "entries": persistentEntries()}
        }) + "\n")
    }

    function mergeLoaded(loadedEntries) {
        const combined = entries.slice()
        const known = ({})
        for (let index = 0; index < combined.length; ++index)
            known[combined[index].id] = true
        for (let index = 0; index < loadedEntries.length; ++index) {
            if (!known[loadedEntries[index].id])
                combined.push(loadedEntries[index])
        }
        combined.sort(function(a, b) { return Number(b.timestamp) - Number(a.timestamp) })
        entries = prune(combined)
    }

    function handleResponse(line) {
        let response
        try {
            response = JSON.parse(line)
        } catch (error) {
            return
        }
        if (!response.ok)
            return
        if (response.op === "state") {
            const state = response.state || ({})
            dndEnabled = Boolean(state.dnd)
            mergeLoaded(Array.isArray(state.entries) ? state.entries : [])
            loaded = true
            if (dirtyBeforeLoad) {
                dirtyBeforeLoad = false
                saveDelay.restart()
            }
        }
    }

    function setDnd(enabled) {
        const clean = Boolean(enabled)
        if (dndEnabled === clean)
            return clean
        dndEnabled = clean
        scheduleSave()
        return clean
    }

    function toggleDnd() {
        return setDnd(!dndEnabled)
    }

    function markAllRead() {
        let changed = false
        const next = entries.map(function(entry) {
            if (entry.read)
                return entry
            changed = true
            return Object.assign({}, entry, {"read": true})
        })
        if (changed) {
            entries = next
            scheduleSave()
        }
    }

    function clearRead() {
        const next = entries.filter(function(entry) { return !entry.read })
        if (next.length !== entries.length) {
            entries = next
            scheduleSave()
        }
    }

    function clearHistory() {
        entries = []
        protocolEntries = ({})
        scheduleSave()
        return true
    }

    function countUnread(source) {
        let count = 0
        for (let index = 0; index < source.length; ++index) {
            if (!source[index].read)
                count += 1
        }
        return count
    }

    function buildGroups(source) {
        const groups = []
        const groupIndexes = ({})
        for (let index = 0; index < source.length; ++index) {
            const entry = source[index]
            const normal = Number(entry.urgency) === Number(NotificationUrgency.Normal)
            const existingIndex = groupIndexes[entry.groupKey]
            if (normal && existingIndex !== undefined) {
                const current = groups[existingIndex]
                if (Number(current.timestamp) - Number(entry.timestamp) <= groupWindowMs) {
                    groups[existingIndex] = Object.assign({}, current, {
                        "groupCount": Number(current.groupCount || 1) + 1,
                        "groupUnread": Number(current.groupUnread || 0) + (entry.read ? 0 : 1)
                    })
                    continue
                }
            }

            const group = Object.assign({}, entry, {
                "groupCount": 1,
                "groupUnread": entry.read ? 0 : 1
            })
            groups.push(group)
            if (normal)
                groupIndexes[entry.groupKey] = groups.length - 1
        }
        return groups
    }

    Timer {
        id: saveDelay
        interval: 350
        repeat: false
        onTriggered: model.saveNow()
    }

    Process {
        id: persistence
        command: ["python", Quickshell.shellPath("state.py"), "serve"]
        stdinEnabled: true
        running: true
        onStarted: write(JSON.stringify({"op": "load"}) + "\n")
        stdout: SplitParser {
            onRead: data => model.handleResponse(data)
        }
    }
}
