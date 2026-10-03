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
    property var savedNetworks: []
    property var ethernet: ({
        "available": false, "connected": false, "device": "", "state": "Unavailable",
        "profile": "", "uuid": "", "ipv4": "", "gateway": ""
    })
    property var connectivity: ({
        "state": "unknown", "captivePortal": false, "limited": false,
        "online": false, "loginAvailable": false
    })
    property string errorText: ""
    property string actionMessage: ""
    property bool statusReady: false
    property bool networksReady: false
    property bool snapshotReady: false
    property string scanState: "unknown"
    property string scanSource: "none"
    property real lastObservationAtMs: 0
    property bool refreshPending: false
    property bool scanning: false
    property bool startupScanAttempted: false
    property string activeAction: ""
    readonly property bool busy: actionProcess.running || scanning

    property string pendingPassword: ""
    property bool ignoreActionResult: false

    signal actionFinished(string action, bool succeeded)
    property bool actionIsScan: false

    function backendPath() {
        return Quickshell.shellPath("wifi.py")
    }

    function refreshStatus() {
        refresh()
    }

    function refreshNetworks() {
        refresh()
    }

    function refresh() {
        if (snapshotProcess.running) {
            state.refreshPending = true
            return
        }
        state.refreshPending = false
        // Keep the last coherent rows in memory, but do not reveal a newly
        // reopened Link surface until this fresh NetworkManager observation
        // completes. Existing visible surfaces keep rendering their last known
        // coherent truth while the non-blocking refresh runs.
        state.statusReady = false
        snapshotProcess.exec(["python", backendPath(), "snapshot"])
    }

    function maybeStartupScan() {
        if (!statusReady
                || !networksReady
                || !available
                || !wifiEnabled
                || scanState !== "warming"
                || startupScanAttempted
                || scanning)
            return
        startupScanAttempted = true
        Qt.callLater(state.rescan)
    }

    function runAction(args, password, isScan) {
        if (actionProcess.running)
            return false
        state.ignoreActionResult = false
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
        if (enabled)
            startupScanAttempted = false
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

    function connectSaved(profileUuid) {
        if (!profileUuid)
            return false
        return runAction(["connect-saved", String(profileUuid)], "", false)
    }

    function forgetSaved(profileUuid) {
        if (!profileUuid)
            return false
        return runAction(["forget", String(profileUuid)], "", false)
    }

    function connectEnterprise(ssid, fields) {
        if (!ssid || !fields)
            return false
        return runAction(["connect-enterprise", String(ssid)], JSON.stringify(fields), false)
    }

    function openCaptivePortal() {
        return runAction(["portal-login"], "", false)
    }

    function cancelPendingConnection() {
        if (!actionProcess.running)
            return false
        const action = String(state.activeAction || "")
        if (action !== "connect" && action !== "connect-saved"
                && action !== "connect-enterprise" && action !== "reconnect")
            return false

        state.pendingPassword = ""
        state.ignoreActionResult = true
        state.actionIsScan = false
        state.scanning = false
        state.activeAction = ""
        state.errorText = ""
        state.actionMessage = ""
        actionProcess.running = false
        state.actionFinished(action, false)
        refreshDelay.restart()
        return true
    }

    Process {
        id: snapshotProcess

        onRunningChanged: {
            if (!running && state.refreshPending)
                Qt.callLater(state.refresh)
        }

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    const observedAt = Number(payload.observedAtMs || 0)
                    if (observedAt > 0 && state.lastObservationAtMs > 0
                            && observedAt < state.lastObservationAtMs) {
                        state.refreshPending = true
                        return
                    }
                    if (observedAt > 0)
                        state.lastObservationAtMs = observedAt

                    state.available = Boolean(payload.available)
                    state.wifiEnabled = Boolean(payload.enabled)
                    state.device = String(payload.device || "")
                    state.currentNetwork = payload.current || null
                    state.networks = payload.networks || []
                    state.savedNetworks = payload.saved || []
                    state.scanState = String(payload.scanState || "unknown")
                    state.scanSource = String(payload.scanSource || "none")
                    state.ethernet = payload.ethernet || ({
                        "available": false, "connected": false, "device": "", "state": "Unavailable",
                        "profile": "", "uuid": "", "ipv4": "", "gateway": ""
                    })
                    state.connectivity = payload.connectivity || ({
                        "state": "unknown", "captivePortal": false, "limited": false,
                        "online": false, "loginAvailable": false
                    })
                    state.errorText = String(payload.error || "")
                    if (!state.available) {
                        state.currentNetwork = null
                        state.networks = []
                        state.savedNetworks = []
                        state.scanState = "unavailable"
                    }
                } catch (error) {
                    state.available = false
                    state.currentNetwork = null
                    state.networks = []
                    state.savedNetworks = []
                    state.scanState = "unavailable"
                    state.scanSource = "none"
                    state.errorText = "Wi-Fi status could not be read."
                    console.log("maho-link snapshot parse:", error)
                }

                // One NetworkManager observation owns all Wi-Fi UI truth.
                // Nearby scan cache may still be warming, but the authoritative
                // current connection is rendered immediately from the same payload.
                state.statusReady = true
                state.networksReady = true
                state.snapshotReady = true
                if (state.scanning)
                    state.scanning = false
                state.maybeStartupScan()
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
                if (state.ignoreActionResult) {
                    state.ignoreActionResult = false
                    return
                }
                const completedAction = state.activeAction
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
                state.actionFinished(completedAction, succeeded)
                state.activeAction = ""
                refreshDelay.restart()
            }
        }
    }

    // NetworkManager owns connectivity truth. Listen to its monitor stream so
    // external nmcli/Settings changes refresh Link immediately; the slow timer
    // below remains only a reconnect/resume fallback.
    Process {
        id: networkManagerMonitor
        command: ["nmcli", "monitor"]
        running: true
        stdout: SplitParser {
            onRead: function(line) {
                if (String(line).length > 0)
                    networkManagerDebounce.restart()
            }
        }
        onRunningChanged: {
            if (!running)
                networkManagerMonitorRestart.restart()
        }
    }

    Timer {
        id: networkManagerDebounce
        interval: 140
        onTriggered: state.refresh()
    }

    Timer {
        id: networkManagerMonitorRestart
        interval: 2500
        onTriggered: {
            if (!networkManagerMonitor.running)
                networkManagerMonitor.running = true
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
