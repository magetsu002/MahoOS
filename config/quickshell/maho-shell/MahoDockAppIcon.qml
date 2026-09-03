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

    readonly property string currentSource:
        candidateIndex >= 0 && candidateIndex < candidates.length
            ? String(candidates[candidateIndex])
            : ""
    readonly property bool ready: artwork.status === Image.Ready

    function appendUnique(output, value) {
        const text = value === undefined || value === null ? "" : String(value).trim()
        if (text.length === 0 || output.indexOf(text) >= 0)
            return
        output.push(text)
    }

    function themed(value) {
        const nameValue = String(value || "").trim()
        if (nameValue.length === 0 || nameValue.startsWith("/") || nameValue.startsWith("file://"))
            return ""
        return Quickshell.iconPath(nameValue, "")
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
        const stem = String(root.entryId || "").replace(/\.desktop$/i, "")
        const parts = stem.split(/[.]/)
        const tail = parts.length > 0 ? parts[parts.length - 1] : ""

        appendUnique(output, themed(rawIcon))
        appendUnique(output, themed(stem))
        appendUnique(output, themed(tail))
        appendUnique(output, themed(normalizedName(root.name)))

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
        anchors.fill: parent
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

    // Unmatched running windows intentionally receive a quiet neutral glyph,
    // not a synthetic app tile pretending to be real artwork.
    Text {
        anchors.centerIn: parent
        visible: !root.ready && root.candidates.length === 0
        text: "◇"
        color: Qt.rgba(1, 1, 1, 0.72)
        font.family: "Inter"
        font.pixelSize: Math.round(Math.min(root.width, root.height) * 0.54)
        font.weight: Font.Light
    }
}
