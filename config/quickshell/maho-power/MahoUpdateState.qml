import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property string authorityState: "NONE"
    property string status: "Healthy"
    property bool activationPending: false
    property bool attentionRequired: false

    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(this.text)
                    state.authorityState = String(data.authority_state || "ATTENTION_REQUIRED")
                    state.status = String(data.status || "Attention required")
                    state.activationPending = data.activation_pending === true
                    state.attentionRequired = data.attention_required === true
                } catch (error) {
                    state.authorityState = "ATTENTION_REQUIRED"
                    state.status = "Attention required"
                    state.attentionRequired = true
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
