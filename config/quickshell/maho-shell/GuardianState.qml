import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property bool enabled: true
    property int highestSeverity: 0
    property int previousSeverity: 0
    property int generation: 0
    property int catastrophicTransitionSerial: 0
    property string signature: ""
    property string candidateSignature: ""
    property int candidateSeverity: 0
    property int candidateSamples: 0

    readonly property bool active: highestSeverity > 0
    readonly property bool presentable: highestSeverity >= 2

    function commitCandidate(nextSignature, highest) {
        const oldSeverity = state.highestSeverity
        state.previousSeverity = oldSeverity
        state.highestSeverity = highest
        state.signature = nextSignature

        if (oldSeverity < 4 && highest === 4)
            state.catastrophicTransitionSerial += 1

        // The Wheel communicates severity escalation, not every provider/
        // incident metadata mutation. Same-level churn remains visible in
        // Guardian itself without replaying the ritual.
        if (highest >= 2 && highest > oldSeverity)
            state.generation += 1
    }

    function applyRows(rows) {
        if (!Array.isArray(rows))
            return

        let highest = 0
        let parts = []

        for (let i = 0; i < rows.length; ++i) {
            const row = rows[i] || {}
            const decision = row.decision || {}
            const severity = decision.severity || {}
            const raw = Number(severity.level)
            const level = isFinite(raw)
                ? Math.max(0, Math.min(4, Math.floor(raw)))
                : 0
            const incidentId = String(row.incident_id || "")
            const mode = String(decision.execution_mode || "observe")

            highest = Math.max(highest, level)
            parts.push(incidentId + ":" + level + ":" + mode)
        }

        parts.sort()
        const nextSignature = parts.join("|")

        // Catastrophic state is never delayed by the startup debounce.
        if (highest === 4) {
            state.candidateSignature = nextSignature
            state.candidateSeverity = highest
            state.candidateSamples = 2
            state.commitCandidate(nextSignature, highest)
            return
        }

        if (nextSignature === state.candidateSignature
                && highest === state.candidateSeverity) {
            state.candidateSamples += 1
        } else {
            state.candidateSignature = nextSignature
            state.candidateSeverity = highest
            state.candidateSamples = 1
        }

        // Two consecutive structured samples are required for L0-L3. This
        // suppresses provider/startup churn without hiding sustained state.
        if (state.candidateSamples < 2)
            return

        if (nextSignature === state.signature && highest === state.highestSeverity)
            return

        state.commitCandidate(nextSignature, highest)
    }

    Process {
        id: reader

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    state.applyRows(JSON.parse(this.text))
                } catch (error) {
                    // Preserve the last known severity on a transient reader
                    // failure. Losing the status command is not evidence that
                    // the incident itself disappeared.
                    console.log("maho-shell Guardian state parse:", error)
                }
            }
        }
    }

    Timer {
        interval: 2000
        repeat: true
        running: state.enabled
        triggeredOnStart: true

        onTriggered: {
            if (reader.running)
                return

            reader.exec([
                Quickshell.env("HOME") + "/.local/bin/maho-guard",
                "guardian-status",
                "--json"
            ])
        }
    }
}
