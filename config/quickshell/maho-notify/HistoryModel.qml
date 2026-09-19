import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.Notifications

Scope {
    id: model

    required property var identityResolver

    readonly property int maxEntries: 500
    readonly property int maxAgeMs: 7 * 24 * 60 * 60 * 1000
    readonly property int groupWindowMs: 2 * 60 * 1000
    property var entries: []
    property bool dndEnabled: false
    property bool loaded: false
    property bool dirtyBeforeLoad: false
    property int serial: 0
    property var protocolEntries: ({})
    property var liveNotifications: ({})
    property var replacementEpochs: ({})
    property var appPolicies: ({})

    signal replayRequested(var entry)
    readonly property int retainedCount: entries.length
    readonly property int unreadCount: countUnread(entries)
    readonly property var groupedEntries: buildGroups(entries)
    readonly property int heldCount: countHeld(entries)
    readonly property int policyCount: Object.keys(appPolicies).length
    readonly property string heldContext: dominantHeldReason(entries)

    onUnreadCountChanged: scheduleStatusPublish()
    onDndEnabledChanged: scheduleStatusPublish()
    onLoadedChanged: scheduleStatusPublish()

    function boundedText(value, maximum) {
        if (value === undefined || value === null)
            return ""
        return String(value).slice(0, maximum)
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

    function snapshot(notification, held, holdReason, deliveryMode) {
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
            "desktopEntry": identityResolver.stableDesktopEntry(notification),
            "icon": identityResolver.stableIconName(notification.appIcon),
            "transient": Boolean(notification.transient),
            "held": Boolean(held),
            "holdReason": boundedText(holdReason || "", 96),
            "deliveryMode": boundedText(deliveryMode || (Boolean(held) ? "held" : "recent"), 32)
        }
    }

    function record(notification, held, holdReason, deliveryMode) {
        if (!notification)
            return

        const protocolKey = String(notification.id)
        const nextLive = Object.assign({}, liveNotifications)
        nextLive[protocolKey] = notification
        liveNotifications = nextLive

        if (protocolEntries[protocolKey] !== undefined) {
            applyReplacement(notification)
            return
        }

        const entry = snapshot(notification, Boolean(held), holdReason || "", deliveryMode || "")
        const nextMap = Object.assign({}, protocolEntries)
        nextMap[protocolKey] = entry.id
        protocolEntries = nextMap

        const next = entries.slice()
        next.unshift(entry)
        entries = prune(next)
        scheduleSave()

        notification.appNameChanged.connect(function() { model.applyReplacement(notification) })
        notification.appIconChanged.connect(function() { model.applyReplacement(notification) })
        notification.desktopEntryChanged.connect(function() { model.applyReplacement(notification) })
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
        const protocolKey = String(notification.id)
        const entryId = protocolEntries[protocolKey]
        const index = entryIndexById(entryId)
        if (index < 0)
            return

        const previous = entries[index]
        const now = Date.now()
        const priorEpoch = Number(replacementEpochs[protocolKey] || 0)
        const nextEpochs = Object.assign({}, replacementEpochs)
        nextEpochs[protocolKey] = now
        replacementEpochs = nextEpochs
        const newGeneration = now - priorEpoch > 50
        const updated = Object.assign({}, previous, {
            "appKey": appKey(notification),
            "appName": boundedText(notification.appName || "Notification", 192),
            "summary": boundedText(notification.summary || notification.appName || "Notification", 512),
            "body": boundedText(notification.body || "", 4096),
            "urgency": Number(notification.urgency),
            "timestamp": now,
            "read": false,
            "groupKey": appKey(notification),
            "replacementCount": Number(previous.replacementCount || 0) + (newGeneration ? 1 : 0),
            "desktopEntry": identityResolver.stableDesktopEntry(notification),
            "icon": identityResolver.stableIconName(notification.appIcon),
            "transient": Boolean(notification.transient),
            "held": Boolean(previous.held),
            "holdReason": boundedText(previous.holdReason || "", 96),
            "deliveryMode": boundedText(previous.deliveryMode || (previous.held ? "held" : "recent"), 32)
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
        if (liveNotifications[protocolKey] === notification) {
            const nextLive = Object.assign({}, liveNotifications)
            delete nextLive[protocolKey]
            liveNotifications = nextLive
        }
        const nextEpochs = Object.assign({}, replacementEpochs)
        delete nextEpochs[protocolKey]
        replacementEpochs = nextEpochs

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
            "state": {
                "version": 5,
                "dnd": dndEnabled,
                "entries": persistentEntries(),
                "policies": appPolicies
            }
        }) + "\n")
    }

    function scheduleStatusPublish() {
        if (!loaded || !persistence.running)
            return
        statusDelay.restart()
    }

    function publishStatus() {
        if (!loaded || !persistence.running)
            return
        persistence.write(JSON.stringify({
            "op": "publish_status",
            "status": {
                "version": 1,
                "unread_count": unreadCount,
                "dnd": dndEnabled,
                "active": true
            }
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
            appPolicies = state.policies && typeof state.policies === "object" ? state.policies : ({})
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

    function markEntryRead(id) {
        const index = entryIndexById(id)
        if (index < 0 || entries[index].read)
            return index >= 0
        const next = entries.slice()
        next[index] = Object.assign({}, next[index], {"read": true})
        entries = next
        scheduleSave()
        return true
    }

    function invokeDefaultAction(notification) {
        if (!notification || !notification.actions)
            return false
        for (let index = 0; index < notification.actions.length; ++index) {
            const action = notification.actions[index]
            if (action && String(action.identifier || "") === "default") {
                action.invoke()
                return true
            }
        }
        return false
    }

    function activateEntry(id) {
        const index = entryIndexById(id)
        if (index < 0)
            return false
        const entry = entries[index]
        const live = liveNotifications[String(entry.protocolId)]
        let activated = false
        try {
            activated = invokeDefaultAction(live)
        } catch (error) {
            activated = false
        }
        if (!activated)
            activated = identityResolver.launchHistory(entry)
        if (activated)
            markEntryRead(id)
        return activated
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

    function clearReadHistory() {
        const next = entries.filter(function(entry) { return entry.held || !entry.read })
        if (next.length !== entries.length) {
            entries = next
            scheduleSave()
            return true
        }
        return false
    }

    function clearAppPolicies() {
        if (Object.keys(appPolicies).length === 0)
            return false
        appPolicies = ({})
        scheduleSave()
        return true
    }

    function clearHistory() {
        entries = []
        protocolEntries = ({})
        liveNotifications = ({})
        replacementEpochs = ({})
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

    function countHeld(source) {
        let count = 0
        for (let index = 0; index < source.length; ++index) {
            if (source[index].held)
                count += 1
        }
        return count
    }

    function dominantHeldReason(source) {
        const counts = ({})
        let best = ""
        let bestCount = 0
        for (let index = 0; index < source.length; ++index) {
            const entry = source[index]
            if (!entry.held)
                continue
            const reason = boundedText(entry.holdReason || "", 96)
            if (reason === "" || reason === "Adaptive Focus" || reason === "Do Not Disturb")
                continue
            counts[reason] = Number(counts[reason] || 0) + 1
            if (counts[reason] > bestCount) {
                best = reason
                bestCount = counts[reason]
            }
        }
        return best
    }

    function policyForKey(key) {
        const clean = boundedText(key || "", 192).toLowerCase()
        const mode = appPolicies[clean]
        return mode === "always-show" || mode === "hold-gaming" || mode === "history-only"
            ? mode : ""
    }

    function policyForNotification(notification) {
        return notification ? policyForKey(appKey(notification)) : ""
    }

    function setAppPolicy(key, mode) {
        const cleanKey = boundedText(key || "", 192).toLowerCase()
        if (cleanKey === "")
            return false
        if (mode !== "always-show" && mode !== "hold-gaming" && mode !== "history-only" && mode !== "")
            return false
        const next = Object.assign({}, appPolicies)
        if (mode === "")
            delete next[cleanKey]
        else
            next[cleanKey] = mode
        appPolicies = next
        scheduleSave()
        return true
    }

    function presentationDecision(notification, dnd, adaptiveQuiet, adaptiveContext) {
        const critical = notification && Number(notification.urgency) === Number(NotificationUrgency.Critical)
        const mode = policyForNotification(notification)
        const context = boundedText(adaptiveContext || "", 96)
        if (critical)
            return {"suppress": false, "held": false, "holdReason": "", "deliveryMode": mode || "recent"}
        if (mode === "history-only")
            return {"suppress": true, "held": false, "holdReason": "", "deliveryMode": mode}
        // Explicit per-app presentation policy is stronger than ambient quiet.
        if (mode === "always-show")
            return {"suppress": false, "held": false, "holdReason": "", "deliveryMode": mode}
        if (mode === "hold-gaming" && Boolean(adaptiveQuiet) && context === "Gaming")
            return {"suppress": true, "held": true, "holdReason": "Gaming", "deliveryMode": mode}
        if (Boolean(dnd))
            return {"suppress": true, "held": true, "holdReason": "Do Not Disturb", "deliveryMode": "held"}
        if (Boolean(adaptiveQuiet))
            return {"suppress": true, "held": true, "holdReason": context || "Adaptive Focus", "deliveryMode": "held"}
        return {"suppress": false, "held": false, "holdReason": "", "deliveryMode": mode || "recent"}
    }

    function releaseHeldModes(modes) {
        let changed = false
        const now = Date.now()
        const next = entries.map(function(entry) {
            if (!entry.held || modes.indexOf(String(entry.deliveryMode || "")) < 0)
                return entry
            changed = true
            return Object.assign({}, entry, {
                "held": false, "holdReason": "", "deliveryMode": "recent", "timestamp": now
            })
        })
        if (changed) {
            next.sort(function(a, b) { return Number(b.timestamp) - Number(a.timestamp) })
            entries = next
            scheduleSave()
        }
        return changed
    }

    function releaseUntilFree() {
        return releaseHeldModes(["hold-until-free"])
    }

    function releaseGamingHolds() {
        return releaseHeldModes(["hold-gaming"])
    }

    function releaseAllHeld() {
        let changed = false
        const now = Date.now()
        const next = entries.map(function(entry) {
            if (!entry.held)
                return entry
            changed = true
            const mode = String(entry.deliveryMode || "")
            const persistentMode = mode === "hold-gaming" ? mode : "recent"
            return Object.assign({}, entry, {
                "held": false,
                "holdReason": "",
                "deliveryMode": persistentMode,
                "timestamp": now
            })
        })
        if (changed) {
            next.sort(function(a, b) { return Number(b.timestamp) - Number(a.timestamp) })
            entries = next
            scheduleSave()
        }
        return changed
    }

    function presentationAction(id, action, adaptiveQuiet, adaptiveContext) {
        const index = entryIndexById(id)
        if (index < 0)
            return false

        const previous = entries[index]
        let patch = ({})
        if (action === "show-now") {
            patch = {"held": false, "holdReason": "", "deliveryMode": "show-now", "read": false, "timestamp": Date.now()}
        } else if (action === "hold-until-free") {
            patch = {"held": true, "holdReason": "Until I'm free", "deliveryMode": action}
        } else if (action === "always-show") {
            setAppPolicy(previous.appKey, action)
            patch = {"held": false, "holdReason": "", "deliveryMode": action}
        } else if (action === "hold-gaming") {
            setAppPolicy(previous.appKey, action)
            const gamingNow = Boolean(adaptiveQuiet) && String(adaptiveContext || "") === "Gaming"
            patch = gamingNow
                ? {"held": true, "holdReason": "Gaming", "deliveryMode": action}
                : {"held": false, "holdReason": "", "deliveryMode": action}
        } else if (action === "history-only") {
            setAppPolicy(previous.appKey, action)
            patch = {"held": false, "holdReason": "", "deliveryMode": action, "read": true}
        } else {
            return false
        }

        const next = entries.slice()
        const updated = Object.assign({}, previous, patch)
        next[index] = updated
        next.sort(function(a, b) { return Number(b.timestamp) - Number(a.timestamp) })
        entries = next
        scheduleSave()
        if (action === "show-now")
            replayRequested(updated)
        return true
    }

    function buildGroups(source) {
        const groups = []
        const groupIndexes = ({})
        for (let index = 0; index < source.length; ++index) {
            const entry = source[index]
            const normal = Number(entry.urgency) === Number(NotificationUrgency.Normal)
            const groupIndexKey = String(entry.groupKey) + "\n" + (entry.held ? "held" : "recent")
            const existingIndex = groupIndexes[groupIndexKey]
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
                "groupUnread": entry.read ? 0 : 1,
                "section": entry.held ? "Held" : "Recent"
            })
            groups.push(group)
            if (normal)
                groupIndexes[groupIndexKey] = groups.length - 1
        }
        const held = groups.filter(function(entry) { return Boolean(entry.held) })
        const recent = groups.filter(function(entry) { return !entry.held })
        return held.concat(recent)
    }

    Timer {
        id: saveDelay
        interval: 350
        repeat: false
        onTriggered: model.saveNow()
    }

    Timer {
        id: statusDelay
        interval: 60
        repeat: false
        onTriggered: model.publishStatus()
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
