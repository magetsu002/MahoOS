import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property bool available: false
    property bool wifiEnabled: false
    property string device: ""
    property var currentNetwork: null
    property var networks: []
    property string errorText: ""
    property string actionMessage: ""
    property bool snapshotReady: false
    readonly property bool busy: snapshotProcess.running || actionProcess.running

    property string pendingPassword: ""

    function backendPath() {
        return Quickshell.shellPath("wifi.py")
    }

    function refresh() {
        if (!snapshotProcess.running)
            snapshotProcess.exec(["python", backendPath(), "snapshot"])
    }

    function runAction(args, password) {
        if (actionProcess.running)
            return false
        actionMessage = ""
        errorText = ""
        pendingPassword = password || ""
        actionProcess.exec(["python", backendPath(), "action"].concat(args))
        return true
    }

    function setWifiEnabled(enabled) {
        return runAction(["toggle", enabled ? "on" : "off"], "")
    }

    function rescan() {
        return runAction(["rescan"], "")
    }

    function disconnect() {
        return runAction(["disconnect", device], "")
    }

    function connectNetwork(ssid, password, hidden) {
        const args = ["connect", String(ssid)]
        if (hidden)
            args.push("hidden")
        return runAction(args, password || "")
    }

    Process {
        id: snapshotProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.available = Boolean(payload.available)
                    state.wifiEnabled = Boolean(payload.enabled)
                    state.device = String(payload.device || "")
                    state.currentNetwork = payload.current || null
                    state.networks = payload.networks || []
                    state.errorText = String(payload.error || "")
                    state.snapshotReady = true
                } catch (error) {
                    state.errorText = "Wi-Fi status could not be read."
                    console.log("maho-link snapshot parse:", error)
                }
            }
        }
    }

    Process {
        id: actionProcess
        stdinEnabled: true

        onStarted: {
            // Secrets stay off argv and out of shell logs.
            write(state.pendingPassword + "\n")
            state.pendingPassword = ""
        }

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    if (payload.ok) {
                        state.actionMessage = String(payload.message || "")
                        state.errorText = ""
                    } else {
                        state.actionMessage = ""
                        state.errorText = String(payload.message || "Wi-Fi action failed.")
                    }
                } catch (error) {
                    state.errorText = "Wi-Fi action returned an invalid response."
                    console.log("maho-link action parse:", error)
                }
                refreshDelay.restart()
            }
        }
    }

    Timer {
        id: refreshDelay
        interval: 320
        onTriggered: state.refresh()
    }

    Timer {
        interval: 7000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: state.refresh()
    }
}
