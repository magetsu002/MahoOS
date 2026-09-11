import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: attention

    FileView {
        id: delivered
        path: Quickshell.statePath("update-attention.json")
        blockLoading: true
        onAdapterUpdated: writeAdapter()

        JsonAdapter {
            id: deliveryState
            property int version: 1
            property string transactionId: ""
        }
    }

    Process {
        id: notifier
    }

    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(this.text)
                    const transaction = String(data.transaction_id || "state-unreadable")
                    if (data.notification_policy !== "one-meaningful-attention"
                            || transaction === deliveryState.transactionId)
                        return
                    deliveryState.transactionId = transaction
                    delivered.writeAdapter()
                    notifier.exec([
                        "notify-send", "--app-name=Maho Update", "--urgency=normal",
                        "Maintenance needs attention", "Open System maintenance to review the blocker."
                    ])
                } catch (error) { }
            }
        }
    }

    Timer {
        interval: 10000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: {
            if (!reader.running && !notifier.running)
                reader.exec([Quickshell.env("HOME") + "/.local/bin/maho-update", "status", "--json"])
        }
    }
}
