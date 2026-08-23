import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property string networkKind: "none"
    property string networkName: ""

    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(this.text)
                    state.networkKind = data.networkKind || "none"
                    state.networkName = data.networkName || ""
                } catch (error) {
                    console.log("maho-shell ambient state parse:", error)
                }
            }
        }
    }

    Timer {
        interval: 1500
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: {
            if (!reader.running)
                reader.exec(["python", Quickshell.shellPath("state.py")])
        }
    }
}
