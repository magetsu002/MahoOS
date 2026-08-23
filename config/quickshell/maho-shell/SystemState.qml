import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property string networkKind: "none"
    property string networkName: ""
    property bool bluetoothAvailable: false
    property bool bluetoothPowered: false
    property bool bluetoothConnected: false
    property int battery: 100
    property bool charging: false
    property bool mediaPlaying: false
    property string mediaTitle: ""
    property string mediaArtist: ""

    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const data = JSON.parse(this.text)
                    state.networkKind = data.networkKind || "none"
                    state.networkName = data.networkName || ""
                    state.bluetoothAvailable = data.bluetoothAvailable || false
                    state.bluetoothPowered = data.bluetoothPowered || false
                    state.bluetoothConnected = data.bluetoothConnected || false
                    state.battery = data.battery ?? 100
                    state.charging = data.charging || false
                    state.mediaPlaying = data.mediaPlaying || false
                    state.mediaTitle = data.mediaTitle || ""
                    state.mediaArtist = data.mediaArtist || ""
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
