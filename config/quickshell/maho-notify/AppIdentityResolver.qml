import QtQuick
import Quickshell

Scope {
    id: resolver

    readonly property int maxIdentityLength: 192
    readonly property int maxIconLength: 512
    property int indexRevision: 0
    property var idIndex: ({})
    property var nameIndex: ({})
    property var genericNameIndex: ({})
    property var startupClassIndex: ({})

    function bounded(value, maximum) {
        if (value === undefined || value === null)
            return ""
        return String(value).slice(0, maximum)
    }

    function normalizeName(value) {
        return bounded(value, maxIdentityLength)
            .trim()
            .toLocaleLowerCase()
            .replace(/\s+/g, " ")
    }

    function normalizeDesktopId(value) {
        let normalized = normalizeName(value)
        if (normalized.endsWith(".desktop"))
            normalized = normalized.slice(0, -8)
        return normalized
    }

    function appendUnique(index, key, entry) {
        if (key === "" || !entry)
            return
        const existing = index[key] || []
        for (let position = 0; position < existing.length; ++position) {
            if (existing[position].id === entry.id)
                return
        }
        existing.push(entry)
        index[key] = existing
    }

    function rebuildIndex() {
        const nextIds = ({})
        const nextNames = ({})
        const nextGenericNames = ({})
        const nextStartupClasses = ({})
        const values = DesktopEntries.applications.values || []

        for (let index = 0; index < values.length; ++index) {
            const entry = values[index]
            if (!entry || !entry.id)
                continue
            appendUnique(nextIds, normalizeDesktopId(entry.id), entry)
            appendUnique(nextNames, normalizeName(entry.name), entry)
            appendUnique(nextGenericNames, normalizeName(entry.genericName), entry)
            appendUnique(nextStartupClasses, normalizeName(entry.startupClass), entry)
        }

        idIndex = nextIds
        nameIndex = nextNames
        genericNameIndex = nextGenericNames
        startupClassIndex = nextStartupClasses
        indexRevision += 1
    }

    function uniqueEntries(groups) {
        const seen = ({})
        const matches = []
        for (let groupIndex = 0; groupIndex < groups.length; ++groupIndex) {
            const group = groups[groupIndex] || []
            for (let index = 0; index < group.length; ++index) {
                const entry = group[index]
                if (!entry || seen[entry.id])
                    continue
                seen[entry.id] = true
                matches.push(entry)
            }
        }
        return matches
    }

    function entryForDesktopId(desktopEntry) {
        const key = normalizeDesktopId(desktopEntry)
        if (key === "")
            return null
        const matches = idIndex[key] || []
        return matches.length === 1 ? matches[0] : null
    }

    function entryForAppName(appName) {
        const key = normalizeName(appName)
        if (key === "")
            return null
        const matches = uniqueEntries([
            nameIndex[key],
            startupClassIndex[key],
            idIndex[normalizeDesktopId(key)],
            genericNameIndex[key]
        ])
        return matches.length === 1 ? matches[0] : null
    }

    function matchedEntry(desktopEntry, appName) {
        // Read the revision so bindings are refreshed when the native model changes.
        const revision = indexRevision
        const direct = entryForDesktopId(desktopEntry)
        return direct || entryForAppName(appName)
    }

    function isNetworkSource(value) {
        const lowered = value.toLocaleLowerCase()
        return lowered.startsWith("http://")
            || lowered.startsWith("https://")
            || lowered.startsWith("ftp://")
    }

    function iconSource(value) {
        const icon = bounded(value, maxIconLength).trim()
        if (icon === "" || isNetworkSource(icon)
                || icon.startsWith("data:") || icon.startsWith("image://"))
            return ""
        if (icon.startsWith("file://"))
            return icon.startsWith("file:///") ? icon : ""
        if (icon.startsWith("file:/") || icon.startsWith("/"))
            return icon
        if (icon.indexOf("://") >= 0 || icon.indexOf("/") >= 0)
            return ""
        return Quickshell.hasThemeIcon(icon) ? Quickshell.iconPath(icon) : ""
    }

    function stableIconName(value) {
        const icon = bounded(value, maxIconLength).trim()
        if (icon === "" || icon.indexOf("/") >= 0 || icon.indexOf(":") >= 0)
            return ""
        return Quickshell.hasThemeIcon(icon) ? icon : ""
    }

    function addCandidate(candidates, source, route, entry) {
        if (source === "")
            return
        for (let index = 0; index < candidates.length; ++index) {
            if (candidates[index].source === source)
                return
        }
        candidates.push({
            "source": source,
            "route": route,
            "desktopEntry": entry ? bounded(entry.id, maxIdentityLength) : "",
            "iconName": entry ? stableIconName(entry.icon) : ""
        })
    }

    function resolve(explicitIcon, desktopEntry, appName) {
        const candidates = []
        addCandidate(candidates, iconSource(explicitIcon), "explicit-icon", null)

        const direct = entryForDesktopId(desktopEntry)
        if (direct)
            addCandidate(candidates, iconSource(direct.icon), "desktop-entry", direct)

        const named = entryForAppName(appName)
        if (named)
            addCandidate(candidates, iconSource(named.icon), "app-name", named)

        return {
            "candidates": candidates,
            "desktopEntry": direct ? bounded(direct.id, maxIdentityLength)
                : (named ? bounded(named.id, maxIdentityLength) : ""),
            "route": candidates.length > 0 ? candidates[0].route : "fallback"
        }
    }

    function resolveNotification(notification) {
        if (!notification)
            return {"candidates": [], "desktopEntry": "", "route": "fallback"}
        return resolve(notification.appIcon, notification.desktopEntry, notification.appName)
    }

    function resolveHistory(entry) {
        if (!entry)
            return {"candidates": [], "desktopEntry": "", "route": "fallback"}
        return resolve(entry.icon, entry.desktopEntry, entry.appName)
    }

    function stableDesktopEntry(notification) {
        if (!notification)
            return ""
        const entry = matchedEntry(notification.desktopEntry, notification.appName)
        return entry ? bounded(entry.id, maxIdentityLength) : ""
    }

    Connections {
        target: DesktopEntries.applications
        function onValuesChanged() { resolver.rebuildIndex() }
    }

    Component.onCompleted: rebuildIndex()
}
