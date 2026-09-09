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

    readonly property bool active: highestSeverity > 0

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
        const oldSeverity = state.highestSeverity

        state.previousSeverity = oldSeverity
        state.highestSeverity = highest

        if (oldSeverity < 4 && highest === 4)
            state.catastrophicTransitionSerial += 1

        if (nextSignature !== state.signature) {
            state.signature = nextSignature
            state.generation += 1
        }
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
