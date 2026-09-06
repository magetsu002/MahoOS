import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

Scope {
    id: root

    required property var dockState

    property string appModelPath: {
        const explicit = Quickshell.env("MAHO_APP_MODEL")
        if (explicit && explicit.length > 0)
            return explicit
        const mahoRoot = Quickshell.env("MAHO_ROOT")
        if (mahoRoot && mahoRoot.length > 0)
            return mahoRoot + "/lib/maho_app_model.py"
        return (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share")
            + "/maho/runtime/current/lib/maho_app_model.py"
    }

    property bool appIndexReady: false
    property string appIndexError: ""
    property var apps: []
    property var appById: ({})
    property var aliasToId: ({})
    property var items: []
    property var mruByAddress: ({})
    property int mruSerial: 0
    property var launching: ({})
    property string pendingFocusAddress: ""

    readonly property int focusedWorkspaceId:
        Hyprland.focusedWorkspace ? Hyprland.focusedWorkspace.id : 0
    readonly property string focusedMonitorName:
        Hyprland.focusedMonitor ? String(Hyprland.focusedMonitor.name || "") : ""

    signal modelChanged()

    function clean(value) {
        return value === undefined || value === null ? "" : String(value)
    }

    function normalizeIdentity(value) {
        let text = clean(value).trim().toLowerCase()
        if (text.endsWith(".desktop"))
            text = text.slice(0, -8)
        return text.replace(/[^a-z0-9]+/g, "")
    }

    function copyMap(source) {
        return Object.assign({}, source || ({}))
    }

    function applyAppIndex(text) {
        try {
            const parsed = JSON.parse(text || "[]")
            root.apps = Array.isArray(parsed) ? parsed : []
            root.appIndexError = ""
        } catch (error) {
            root.apps = []
            root.appIndexError = "Application index unavailable"
            console.warn("Maho Dock application index parse failed:", error)
        }

        const byId = ({})
        const aliases = ({})
        for (let index = 0; index < root.apps.length; ++index) {
            const app = root.apps[index]
            const id = clean(app.id)
            if (id.length === 0)
                continue
            byId[id] = app
            const candidates = Array.isArray(app.aliases) ? app.aliases : []
            for (let aliasIndex = 0; aliasIndex < candidates.length; ++aliasIndex) {
                const alias = normalizeIdentity(candidates[aliasIndex])
                if (alias.length > 0)
                    aliases[alias] = id
            }
        }
        root.appById = byId
        root.aliasToId = aliases
        root.appIndexReady = true
        seedDefaultPins()
        rebuild()
    }

    function resolveSeedGroup(group) {
        for (let index = 0; index < group.length; ++index) {
            const alias = normalizeIdentity(group[index])
            if (root.aliasToId[alias])
                return root.aliasToId[alias]
        }

        for (let appIndex = 0; appIndex < root.apps.length; ++appIndex) {
            const app = root.apps[appIndex]
            const name = normalizeIdentity(app.name)
            for (let groupIndex = 0; groupIndex < group.length; ++groupIndex) {
                if (name === normalizeIdentity(group[groupIndex]))
                    return clean(app.id)
            }
        }
        return ""
    }

    function seedDefaultPins() {
        if (!root.appIndexReady || root.dockState.seeded)
            return

        // These are only first-run preferences. Resolved real desktop IDs are
        // persisted immediately; nothing here remains a permanent hardcoded pin.
        const groups = [
            ["kitty", "terminal", "org.gnome.Terminal"],
            ["chatgpt", "com.openai.chatgpt", "openai"],
            ["firefox", "org.mozilla.firefox"],
            ["code", "vscode", "visual studio code", "com.visualstudio.code"],
            ["spotify", "com.spotify.Client"],
            ["system settings", "systemsettings", "gnome-control-center"]
        ]

        const output = []
        for (let index = 0; index < groups.length; ++index) {
            const id = resolveSeedGroup(groups[index])
            if (id.length > 0 && output.indexOf(id) < 0)
                output.push(id)
        }
        root.dockState.seedPins(output)
    }

    function identityForToplevel(toplevel) {
        if (!toplevel)
            return ({ "appId": "", "className": "", "identity": "" })

        const ipc = toplevel.lastIpcObject || ({})
        const waylandId = toplevel.wayland ? clean(toplevel.wayland.appId) : ""
        const candidates = [
            clean(ipc.class),
            clean(ipc.initialClass),
            waylandId
        ]

        for (let index = 0; index < candidates.length; ++index) {
            const normalized = normalizeIdentity(candidates[index])
            if (normalized.length > 0 && root.aliasToId[normalized]) {
                return ({
                    "appId": root.aliasToId[normalized],
                    "className": candidates[index],
                    "identity": normalized
                })
            }
        }

        for (let index = 0; index < candidates.length; ++index) {
            const normalized = normalizeIdentity(candidates[index])
            if (normalized.length > 0) {
                return ({
                    "appId": "",
                    "className": candidates[index],
                    "identity": normalized
                })
            }
        }

        return ({ "appId": "", "className": "", "identity": "" })
    }

    function windowRecord(toplevel) {
        const ipc = toplevel.lastIpcObject || ({})
        const identity = identityForToplevel(toplevel)
        return {
            "toplevel": toplevel,
            "address": clean(toplevel.address),
            "title": clean(toplevel.title),
            "className": identity.className,
            "identity": identity.identity,
            "appId": identity.appId,
            "workspaceId": toplevel.workspace ? Number(toplevel.workspace.id || 0) : 0,
            "workspaceName": toplevel.workspace ? clean(toplevel.workspace.name) : "",
            "monitorName": toplevel.monitor ? clean(toplevel.monitor.name) : "",
            "activated": Boolean(toplevel.activated),
            "urgent": Boolean(toplevel.urgent),
            "pid": Number(ipc.pid || 0),
            "mru": Number(root.mruByAddress[clean(toplevel.address)] || 0)
        }
    }

    function bestWindow(windows) {
        if (!windows || windows.length === 0)
            return null
        const sorted = windows.slice(0)
        sorted.sort(function(first, second) {
            if (Boolean(first.activated) !== Boolean(second.activated))
                return first.activated ? -1 : 1
            if (Number(first.mru || 0) !== Number(second.mru || 0))
                return Number(second.mru || 0) - Number(first.mru || 0)
            const firstHere = Number(first.workspaceId || 0) === root.focusedWorkspaceId
            const secondHere = Number(second.workspaceId || 0) === root.focusedWorkspaceId
            if (firstHere !== secondHere)
                return firstHere ? -1 : 1
            return clean(first.address).localeCompare(clean(second.address))
        })
        return sorted[0]
    }

    function displayNameForClass(value) {
        const raw = clean(value).trim()
        if (raw.length === 0)
            return "Application"
        const spaced = raw.replace(/[._-]+/g, " ").trim()
        return spaced.length > 0
            ? spaced.replace(/\b\w/g, function(letter) { return letter.toUpperCase() })
            : raw
    }

    function makeItem(id, app, windows, pinned, temporary) {
        const rows = windows || []
        const focused = rows.some(function(window) { return Boolean(window.activated) })
        const onFocusedWorkspace = rows.some(function(window) {
            return Number(window.workspaceId || 0) === root.focusedWorkspaceId
        })
        const running = rows.length > 0

        return {
            "id": id,
            "name": app ? clean(app.name) : displayNameForClass(rows.length > 0 ? rows[0].className : id),
            "icon": app ? clean(app.icon) : "",
            "iconPath": app ? clean(app.iconPath) : "",
            "desktopFile": app ? clean(app.desktopFile) : "",
            "pinned": Boolean(pinned),
            "temporary": Boolean(temporary),
            "running": running,
            "launching": !running && Boolean(root.launching[id]),
            "focused": focused,
            "onOtherWorkspace": running && !onFocusedWorkspace,
            "windowCount": rows.length,
            "windows": rows,
            "bestWindow": bestWindow(rows),
            "breakBefore": false
        }
    }

    function rebuild() {
        const grouped = ({})
        const temporaryMeta = ({})
        const source = Hyprland.toplevels.values || []

        for (let index = 0; index < source.length; ++index) {
            const top = source[index]
            if (!top || clean(top.address).length === 0)
                continue
            const window = windowRecord(top)
            if (window.appId.length > 0) {
                if (!grouped[window.appId])
                    grouped[window.appId] = []
                grouped[window.appId].push(window)
                if (root.launching[window.appId]) {
                    const launches = copyMap(root.launching)
                    delete launches[window.appId]
                    root.launching = launches
                }
            } else if (window.identity.length > 0) {
                const temporaryId = "window:" + window.identity
                if (!grouped[temporaryId])
                    grouped[temporaryId] = []
                grouped[temporaryId].push(window)
                temporaryMeta[temporaryId] = window.className
            }
        }

        const output = []
        const represented = ({})
        const pins = root.dockState.pins || []

        for (let index = 0; index < pins.length; ++index) {
            const id = clean(pins[index])
            const app = root.appById[id]
            if (!app)
                continue
            output.push(makeItem(id, app, grouped[id] || [], true, false))
            represented[id] = true
        }

        const runningIds = Object.keys(grouped).filter(function(id) { return !represented[id] })
        runningIds.sort(function(first, second) {
            const firstWindows = grouped[first] || []
            const secondWindows = grouped[second] || []
            const firstFocused = firstWindows.some(function(window) { return window.activated })
            const secondFocused = secondWindows.some(function(window) { return window.activated })
            if (firstFocused !== secondFocused)
                return firstFocused ? -1 : 1

            const firstBest = bestWindow(firstWindows)
            const secondBest = bestWindow(secondWindows)
            if (Number(firstBest ? firstBest.mru : 0) !== Number(secondBest ? secondBest.mru : 0))
                return Number(secondBest ? secondBest.mru : 0) - Number(firstBest ? firstBest.mru : 0)

            const firstApp = root.appById[first]
            const secondApp = root.appById[second]
            const firstName = firstApp ? clean(firstApp.name) : displayNameForClass(temporaryMeta[first] || first)
            const secondName = secondApp ? clean(secondApp.name) : displayNameForClass(temporaryMeta[second] || second)
            return firstName.localeCompare(secondName)
        })

        let insertedDynamic = false
        for (let index = 0; index < runningIds.length; ++index) {
            const id = runningIds[index]
            const app = root.appById[id] || null
            const item = makeItem(id, app, grouped[id] || [], false, !app)
            item.breakBefore = !insertedDynamic && output.length > 0
            insertedDynamic = true
            output.push(item)
        }

        root.items = output
        root.modelChanged()
    }

    function recordActiveToplevel() {
        const active = Hyprland.activeToplevel
        if (!active || clean(active.address).length === 0)
            return
        root.mruSerial += 1
        const next = copyMap(root.mruByAddress)
        next[clean(active.address)] = root.mruSerial
        root.mruByAddress = next
    }

    function launchApp(id, newInstance) {
        const app = root.appById[id]
        if (!app)
            return

        const next = copyMap(root.launching)
        next[id] = Date.now()
        root.launching = next
        launchExpiry.restart()
        rebuild()
        Quickshell.execDetached([
            "python3", root.appModelPath,
            newInstance ? "launch-new" : "launch-app",
            id
        ])
    }

    function focusWindow(window) {
        if (!window || !window.toplevel)
            return

        const address = clean(window.address)
        if (address.length === 0)
            return

        root.pendingFocusAddress = address
        const targetWorkspace = window.toplevel.workspace
        if (targetWorkspace && !targetWorkspace.focused) {
            targetWorkspace.activate()
            focusDelay.restart()
        } else {
            focusDelay.interval = 1
            focusDelay.restart()
        }
    }

    function activateItem(item, newWindow) {
        if (!item)
            return

        if (newWindow) {
            if (!item.temporary)
                launchApp(clean(item.id), true)
            return
        }

        if (!item.running) {
            if (!item.temporary)
                launchApp(clean(item.id), false)
            return
        }

        const target = item.bestWindow || bestWindow(item.windows)
        focusWindow(target)
    }

    function pinItem(item) {
        if (item && !item.temporary)
            root.dockState.pin(clean(item.id))
    }

    function unpinItem(item) {
        if (item)
            root.dockState.unpin(clean(item.id))
    }

    Process {
        id: appIndex
        command: ["python3", root.appModelPath, "apps"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: root.applyAppIndex(text)
        }
        stderr: StdioCollector {
            onStreamFinished: {
                if (text.trim().length > 0)
                    console.warn("Maho Dock app model:", text.trim())
            }
        }
    }

    Timer {
        id: eventRefresh
        interval: 45
        repeat: false
        onTriggered: {
            // Refresh workspaces first: older Quickshell builds expect workspace
            // objects to exist before fresh toplevel IPC objects reference them.
            Hyprland.refreshWorkspaces()
            Hyprland.refreshToplevels()
            rebuildDelay.restart()
        }
    }

    Timer {
        id: rebuildDelay
        interval: 35
        repeat: false
        onTriggered: root.rebuild()
    }

    Timer {
        id: focusDelay
        interval: 42
        repeat: false
        onTriggered: {
            const address = root.pendingFocusAddress
            root.pendingFocusAddress = ""
            focusDelay.interval = 42
            if (address.length > 0)
                Hyprland.dispatch("focuswindow address:" + address)
        }
    }

    Timer {
        id: launchExpiry
        interval: 6500
        repeat: false
        onTriggered: {
            const now = Date.now()
            const next = ({})
            const ids = Object.keys(root.launching)
            for (let index = 0; index < ids.length; ++index) {
                const id = ids[index]
                if (now - Number(root.launching[id] || 0) < 6200)
                    next[id] = root.launching[id]
            }
            root.launching = next
            root.rebuild()
        }
    }

    Connections {
        target: root.dockState
        function onPinsChangedByUser() { root.rebuild() }
    }

    Connections {
        target: Hyprland

        function onActiveToplevelChanged() {
            root.recordActiveToplevel()
            root.rebuild()
        }

        function onFocusedWorkspaceChanged() {
            root.rebuild()
        }

        function onRawEvent(event) {
            const name = clean(event.name)
            // Window-title churn is display metadata, not Dock identity/state.
            // Browsers/media apps can emit it repeatedly while the pointer is
            // stationary; rebuilding the whole array then destroys the hovered
            // delegate and cancels hover intent. Preview cards read the live
            // toplevel title directly instead.
            const relevant = [
                "openwindow", "closewindow", "movewindow", "movewindowv2",
                "activewindow", "activewindowv2", "workspace", "workspacev2",
                "fullscreen"
            ]
            if (relevant.indexOf(name) >= 0)
                eventRefresh.restart()
        }
    }

    Component.onCompleted: {
        root.recordActiveToplevel()
        eventRefresh.restart()
    }
}
