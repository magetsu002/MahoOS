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
    property bool statusReady: false
    property bool networksReady: false
    property bool snapshotReady: false
    property bool scanning: false
    property string activeAction: ""
    readonly property bool busy: actionProcess.running || scanning

    property string pendingPassword: ""
    property bool actionIsScan: false

    function backendPath() {
        return Quickshell.shellPath("wifi.py")
    }

    function mergeStatusCurrent(candidate) {
        if (!candidate)
            return null
        if (state.currentNetwork
                && String(state.currentNetwork.ssid || "") === String(candidate.ssid || "")
                && Number(state.currentNetwork.signal) >= 0) {
            const merged = Object.assign({}, state.currentNetwork)
            merged.state = String(candidate.state || merged.state || "Connected")
            merged.ipv4 = String(candidate.ipv4 || merged.ipv4 || "")
            merged.gateway = String(candidate.gateway || merged.gateway || "")
            return merged
        }
        return candidate
    }

    function refreshStatus() {
        if (!statusProcess.running)
            statusProcess.exec(["python", backendPath(), "status"])
    }

    function refreshNetworks() {
        if (!networkProcess.running)
            networkProcess.exec(["python", backendPath(), "networks"])
    }

    function refresh() {
        refreshStatus()
        refreshNetworks()
    }

    function runAction(args, password, isScan) {
        if (actionProcess.running)
            return false
        statusClearTimer.stop()
        actionMessage = ""
        errorText = ""
        pendingPassword = password || ""
        actionIsScan = Boolean(isScan)
        activeAction = args && args.length > 0 ? String(args[0]) : ""
        if (actionIsScan)
            scanning = true
        actionProcess.exec(["python", backendPath(), "action"].concat(args))
        return true
    }

    function setWifiEnabled(enabled) {
        return runAction(["toggle", enabled ? "on" : "off"], "", false)
    }

    function rescan() {
        return runAction(["rescan"], "", true)
    }

    function disconnect() {
        return runAction(["disconnect", device], "", false)
    }

    function reconnect() {
        if (!currentNetwork || !device)
            return false
        return runAction(["reconnect"], "", false)
    }

    function connectNetwork(ssid, password, hidden) {
        const args = ["connect", String(ssid)]
        if (hidden)
            args.push("hidden")
        return runAction(args, password || "", false)
    }

    Process {
        id: statusProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.available = Boolean(payload.available)
                    state.wifiEnabled = Boolean(payload.enabled)
                    state.device = String(payload.device || "")
                    state.currentNetwork = state.mergeStatusCurrent(payload.current || null)
                    state.errorText = String(payload.error || "")
                } catch (error) {
                    state.available = false
                    state.errorText = "Wi-Fi status could not be read."
                    console.log("maho-link status parse:", error)
                }
                // This is the authoritative gate for showing the Wi-Fi surface.
                // Nearby-network discovery is deliberately not part of it.
                state.statusReady = true
                state.snapshotReady = true
            }
        }
    }

    Process {
        id: networkProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.networks = payload.networks || []
                    if (payload.current)
                        state.currentNetwork = payload.current
                    state.networksReady = true
                    state.snapshotReady = state.statusReady
                    if (state.errorText === "")
                        state.errorText = String(payload.error || "")
                } catch (error) {
                    console.log("maho-link network parse:", error)
                }
                if (state.scanning)
                    state.scanning = false
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
                let succeeded = false
                try {
                    const payload = JSON.parse(this.text)
                    succeeded = Boolean(payload.ok)
                    if (payload.ok) {
                        state.actionMessage = String(payload.message || "")
                        state.errorText = ""
                        if (state.actionMessage !== "")
                            statusClearTimer.restart()
                    } else {
                        statusClearTimer.stop()
                        state.actionMessage = ""
                        state.errorText = String(payload.message || "Wi-Fi action failed.")
                    }
                } catch (error) {
                    statusClearTimer.stop()
                    state.errorText = "Wi-Fi action returned an invalid response."
                    console.log("maho-link action parse:", error)
                }
                if (state.actionIsScan && !succeeded)
                    state.scanning = false
                state.activeAction = ""
                refreshDelay.restart()
            }
        }
    }

    Timer {
        id: statusClearTimer
        interval: 1500
        onTriggered: {
            if (state.errorText === "")
                state.actionMessage = ""
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
