import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root

    property int mode: 0
    property string query: ""
    property int maximumResults: 60
    property string backendPath: (Quickshell.env("MAHO_ROOT") || "") + "/lib/maho_launcher_backend.py"
    property string fileQueryInFlight: ""
    property bool fileSearchBusy: false

    signal closeRequested()
    signal modelChanged()

    ScriptModel { id: appModel }
    ScriptModel { id: fileModel }
    ScriptModel { id: commandModel }

    property alias apps: appModel
    property alias files: fileModel
    property alias commands: commandModel

    readonly property var activeModel: mode === 0 ? appModel : (mode === 1 ? fileModel : commandModel)

    function cleanString(value) {
        if (value === undefined || value === null)
            return ""
        const text = String(value)
        return text === "[object Object]" ? "" : text
    }

    function cleanStringList(value) {
        if (!value || value.length === undefined)
            return []
        const output = []
        for (let index = 0; index < value.length; ++index) {
            const text = cleanString(value[index])
            if (text.length > 0)
                output.push(text)
        }
        return output
    }

    // ScriptModel is deliberately fed plain snapshots instead of live
    // DesktopEntry QObjects. This keeps delegate roles deterministic across
    // Quickshell versions and fixes blank text/generic white icon rows.
    function snapshotApplication(entry) {
        return {
            "id": cleanString(entry.id),
            "name": cleanString(entry.name),
            "genericName": cleanString(entry.genericName),
            "comment": cleanString(entry.comment),
            "icon": cleanString(entry.icon),
            "keywords": cleanStringList(entry.keywords),
            "categories": cleanStringList(entry.categories)
        }
    }

    function descriptionFor(entry) {
        if (entry.genericName && entry.genericName.trim().length > 0)
            return entry.genericName.trim()
        if (entry.comment && entry.comment.trim().length > 0)
            return entry.comment.trim()
        return "Application"
    }

    function appSearchText(entry) {
        const keywords = entry.keywords ? entry.keywords.join(" ") : ""
        const categories = entry.categories ? entry.categories.join(" ") : ""
        return (cleanString(entry.name) + " " + cleanString(entry.genericName) + " " + cleanString(entry.comment)
            + " " + keywords + " " + categories).toLowerCase()
    }

    function fuzzyScore(label, haystack, rawQuery) {
        const queryText = rawQuery.trim().toLowerCase()
        if (queryText.length === 0)
            return 0

        const name = label.toLowerCase()
        const search = haystack.toLowerCase()
        if (name === queryText)
            return 10000
        if (name.startsWith(queryText))
            return 8000 - name.length * 0.1
        if (name.indexOf(queryText) >= 0)
            return 6500 - name.indexOf(queryText) * 8

        const words = name.split(/[\s._-]+/)
        for (let wordIndex = 0; wordIndex < words.length; ++wordIndex) {
            if (words[wordIndex].startsWith(queryText))
                return 5900 - wordIndex * 20
        }

        if (search.indexOf(queryText) >= 0)
            return 4400 - search.indexOf(queryText) * 2

        let queryIndex = 0
        let previous = -1
        let gaps = 0
        let streak = 0
        for (let index = 0; index < search.length && queryIndex < queryText.length; ++index) {
            if (search[index] !== queryText[queryIndex])
                continue
            if (previous >= 0) {
                const distance = index - previous - 1
                gaps += distance
                if (distance === 0)
                    streak += 14
            }
            previous = index
            queryIndex += 1
        }
        if (queryIndex !== queryText.length)
            return -1
        return 1800 + streak - gaps * 6 - search.length * 0.02
    }

    function usageBoost(id) {
        const launches = history.launches || ({})
        const item = launches[id]
        if (!item)
            return 0
        const count = Math.min(40, Number(item.count || 0))
        const last = Number(item.last || 0)
        const ageHours = last > 0 ? Math.max(0, (Date.now() - last) / 3600000) : 99999
        const recent = ageHours < 2 ? 520 : (ageHours < 24 ? 320 : (ageHours < 168 ? 130 : 0))
        return count * 18 + recent
    }

    function rememberLaunch(id) {
        if (!id)
            return
        const launches = Object.assign({}, history.launches || ({}))
        const previous = launches[id] || ({ "count": 0, "last": 0 })
        launches[id] = {
            "count": Number(previous.count || 0) + 1,
            "last": Date.now()
        }
        history.launches = launches
    }

    function refilterApps() {
        const source = DesktopEntries.applications.values || []
        const matches = []
        for (let index = 0; index < source.length; ++index) {
            const entry = source[index]
            const name = entry ? cleanString(entry.name) : ""
            if (!entry || entry.noDisplay || name.length === 0)
                continue
            const score = fuzzyScore(name, appSearchText(entry), query)
            if (score < 0)
                continue
            const id = cleanString(entry.id)
            matches.push({
                "entry": entry,
                "score": score + usageBoost(id)
            })
        }

        matches.sort(function(first, second) {
            if (first.score !== second.score)
                return second.score - first.score
            return cleanString(first.entry.name).localeCompare(cleanString(second.entry.name))
        })

        const output = []
        for (let result = 0; result < Math.min(maximumResults, matches.length); ++result)
            output.push(snapshotApplication(matches[result].entry))
        appModel.values = output
        modelChanged()
    }

    function refilterCommands() {
        const source = [
            { "id": "terminal", "name": "Terminal", "description": "Open a terminal session", "icon": "utilities-terminal" },
            { "id": "files", "name": "File Manager", "description": "Browse your home folder", "icon": "system-file-manager" },
            { "id": "lock", "name": "Lock Screen", "description": "Secure this session", "icon": "system-lock-screen" },
            { "id": "diagnostics", "name": "Launcher Diagnostics", "description": "Inspect Maho Launcher health", "icon": "utilities-system-monitor" }
        ]
        const output = []
        for (let index = 0; index < source.length; ++index) {
            const item = source[index]
            const score = fuzzyScore(item.name, item.name + " " + item.description, query)
            if (score >= 0)
                output.push({ "item": item, "score": score })
        }
        output.sort(function(a, b) {
            if (a.score !== b.score)
                return b.score - a.score
            return a.item.name.localeCompare(b.item.name)
        })
        commandModel.values = output.map(function(row) { return row.item })
        modelChanged()
    }

    function requestFileSearch() {
        if (mode !== 1)
            return
        fileDebounce.restart()
    }

    function runFileSearch() {
        if (fileSearch.running) {
            fileDebounce.restart()
            return
        }
        fileQueryInFlight = query
        fileSearch.command = ["python3", backendPath, "files", "--query", fileQueryInFlight, "--limit", String(maximumResults)]
        fileSearchBusy = true
        fileSearch.running = true
    }

    function applyFileResults(text) {
        fileSearchBusy = false
        if (mode !== 1)
            return
        if (fileQueryInFlight !== query) {
            fileDebounce.restart()
            return
        }
        try {
            const parsed = JSON.parse(text || "[]")
            fileModel.values = Array.isArray(parsed) ? parsed : []
        } catch (error) {
            console.warn("Maho Launcher file search parse failed:", error)
            fileModel.values = []
        }
        modelChanged()
    }

    function activate(item) {
        if (!item)
            return

        if (mode === 0) {
            rememberLaunch(item.id)
            Quickshell.execDetached(["python3", backendPath, "launch-app", item.id])
            closeRequested()
            return
        }

        if (mode === 1) {
            Quickshell.execDetached(["python3", backendPath, "open-path", item.path])
            closeRequested()
            return
        }

        Quickshell.execDetached(["python3", backendPath, "command", item.id])
        closeRequested()
    }

    function displayName(item) {
        return item ? cleanString(item.name) : ""
    }

    function displayDescription(item) {
        if (!item)
            return ""
        if (mode === 0)
            return descriptionFor(item)
        return cleanString(item.description)
    }

    function iconName(item) {
        if (!item)
            return ""
        if (mode === 0)
            return cleanString(item.icon)
        return cleanString(item.icon) || (mode === 1 ? "text-x-generic" : "system-run")
    }

    onQueryChanged: {
        if (mode === 0)
            refilterApps()
        else if (mode === 1)
            requestFileSearch()
        else
            refilterCommands()
    }

    onModeChanged: {
        if (mode === 0)
            refilterApps()
        else if (mode === 1)
            requestFileSearch()
        else
            refilterCommands()
    }

    Connections {
        target: DesktopEntries.applications
        function onValuesChanged() {
            if (root.mode === 0)
                root.refilterApps()
        }
    }

    Timer {
        id: fileDebounce
        interval: 125
        repeat: false
        onTriggered: root.runFileSearch()
    }

    Process {
        id: fileSearch
        running: false
        stdout: StdioCollector {
            onStreamFinished: root.applyFileResults(text)
        }
    }

    FileView {
        path: Quickshell.statePath("launcher-history.json")
        blockLoading: true
        onAdapterUpdated: writeAdapter()

        JsonAdapter {
            id: history
            property var launches: ({})
        }
    }

    Component.onCompleted: {
        refilterApps()
        refilterCommands()
    }
}
