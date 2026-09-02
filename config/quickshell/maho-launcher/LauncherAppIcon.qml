import QtQuick
import Quickshell
import Quickshell.Widgets

Item {
    id: root

    required property string name
    required property string entryId
    required property string icon
    required property string iconPath

    property var candidates: []
    property int candidateIndex: 0

    readonly property string currentSource: candidateIndex >= 0 && candidateIndex < candidates.length
        ? String(candidates[candidateIndex])
        : ""
    readonly property bool ready: artwork.status === Image.Ready

    function appendUnique(output, value) {
        const text = value === undefined || value === null ? "" : String(value).trim()
        if (text.length === 0 || output.indexOf(text) >= 0)
            return
        output.push(text)
    }

    function themed(nameValue) {
        const value = nameValue === undefined || nameValue === null ? "" : String(nameValue).trim()
        if (value.length === 0 || value.startsWith("/") || value.startsWith("file://"))
            return ""
        return Quickshell.iconPath(value, "")
    }

    function withoutDesktopSuffix(value) {
        return String(value || "").replace(/\.desktop$/i, "")
    }

    function normalizedName(value) {
        return String(value || "")
            .trim()
            .replace(/[^A-Za-z0-9._-]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .toLowerCase()
    }

    function rebuildCandidates() {
        const output = []
        const rawIcon = String(root.icon || "").trim()
        const idStem = withoutDesktopSuffix(root.entryId)
        const idParts = idStem.split(/[.]/)
        const idTail = idParts.length > 0 ? idParts[idParts.length - 1] : ""
        const appSlug = normalizedName(root.name)

        // Prefer the active icon theme before any raw legacy artwork. This keeps
        // applications visually native and avoids old hicolor assets that bake
        // opaque white plates into the image itself.
        appendUnique(output, themed(rawIcon))
        appendUnique(output, themed(idStem))
        appendUnique(output, themed(idTail))
        appendUnique(output, themed(appSlug))

        // Then use the exact artwork supplied by the desktop entry/backend.
        // These are still real application assets, never synthetic placeholders.
        if (rawIcon.startsWith("/") || rawIcon.startsWith("file://"))
            appendUnique(output, rawIcon)
        appendUnique(output, root.iconPath)

        root.candidates = output
        root.candidateIndex = 0
    }

    function tryNext() {
        if (root.candidateIndex + 1 < root.candidates.length)
            root.candidateIndex += 1
        else
            root.candidateIndex = root.candidates.length
    }

    onNameChanged: rebuildCandidates()
    onEntryIdChanged: rebuildCandidates()
    onIconChanged: rebuildCandidates()
    onIconPathChanged: rebuildCandidates()
    Component.onCompleted: rebuildCandidates()

    IconImage {
        id: artwork
        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        source: root.currentSource
        visible: root.ready
        asynchronous: true
        mipmap: true
        smooth: true

        onStatusChanged: {
            if (status === Image.Error)
                root.tryNext()
        }
    }
}
