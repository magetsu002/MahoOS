import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property string transactionId: ""
    property string authorityState: "NONE"
    property string status: "Healthy"
    property string lastMaintenance: ""
    property bool activationPending: false
    property bool attentionRequired: false
    property var blockers: []
    property int historyCount: 0

    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(this.text)
                    state.transactionId = String(data.transaction_id || "")
                    state.authorityState = String(data.authority_state || "ATTENTION_REQUIRED")
                    state.status = String(data.status || "Attention required")
                    state.lastMaintenance = String(data.last_maintenance || "")
                    state.activationPending = data.activation_pending === true
                    state.attentionRequired = data.attention_required === true
                    state.blockers = Array.isArray(data.blockers) ? data.blockers : ["authoritative_update_state_invalid"]
                    state.historyCount = Number(data.history_count || 0)
                } catch (error) {
                    state.authorityState = "ATTENTION_REQUIRED"
                    state.status = "Attention required"
                    state.attentionRequired = true
                    state.blockers = ["authoritative_update_state_unreadable"]
                }
            }
        }
    }

    Timer {
        interval: 10000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: {
            if (!reader.running)
                reader.exec([Quickshell.env("HOME") + "/.local/bin/maho-update", "status", "--json"])
        }
    }
}
