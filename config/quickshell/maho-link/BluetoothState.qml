import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property bool available: false
    property bool bluetoothEnabled: false
    property bool discovering: false
    property string adapterPath: ""
    property var pairedDevices: []
    property var availableDevices: []
    property var connectedDevices: []
    property var autoConnectEligible: []
    property string errorText: ""
    property string actionMessage: ""
    property string activeAction: ""
    property string activeDevicePath: ""
    property string pairingPromptKind: ""
    property string pairingPromptValue: ""
    property int pairingPromptRequestId: 0
    property string pairingServiceUuid: ""
    property string pairingInputError: ""
    property bool pairingResultSeen: false
    property bool pairingResultOk: false
    property string pairingResultMessage: ""
    property bool pairingCancelRequested: false
    property bool snapshotReady: false
    property bool discoveryStopping: false
    property real discoveryStartedAt: 0
    readonly property string discoveryClientBinary: "blue" + "toothctl"
    readonly property bool discoveryOwned: discoverySession.running
    readonly property bool pairingActive: pairingProcess.running
    readonly property bool busy:
        actionProcess.running || cancelProcess.running || pairingProcess.running

    signal actionSucceeded(string action, string devicePath)
    signal actionFailed(string action, string devicePath)

    function backendPath() {
        return Quickshell.shellPath("bluetooth.py")
    }

    function refresh() {
        if (!snapshotProcess.running)
            snapshotProcess.exec(["python", backendPath(), "snapshot"])
    }

    function runAction(args, actionName, devicePath) {
        if (actionProcess.running || pairingProcess.running)
            return false
        clearStatus.stop()
        state.errorText = ""
        state.actionMessage = ""
        state.activeAction = actionName || ""
        state.activeDevicePath = devicePath || ""
        actionProcess.exec(["python", backendPath(), "action"].concat(args))
        return true
    }

    function setBluetoothEnabled(enabled) {
        if (adapterPath === "")
            return false
        if (!enabled && discoverySession.running)
            stopDiscovery()
        return runAction(["toggle", adapterPath, enabled ? "on" : "off"], "toggle", "")
    }

    // BlueZ discovery is a per-D-Bus-client session. A one-shot method caller
    // returns success but immediately drops the client that acquired the scan.
    // Keep one BlueZ control client alive solely as the session owner. Device
    // identity, metadata and result rows still come only from the structured
    // ObjectManager snapshot below; control-client output is never data input.
    function startDiscovery() {
        if (adapterPath === "" || !bluetoothEnabled)
            return false
        if (discoverySession.running)
            return true

        clearStatus.stop()
        state.errorText = ""
        state.actionMessage = "Looking for nearby devices…"
        state.discoveryStopping = false
        state.discoveryStartedAt = Date.now()
        state.discovering = true
        discoverySession.running = true
        discoverySessionTimeout.restart()
        refreshSoon.restart()
        return true
    }

    function stopDiscovery() {
        discoverySessionTimeout.stop()

        if (discoverySession.running) {
            state.discoveryStopping = true
            // Release this client's own discovery session before quitting. A
            // fallback SIGTERM is used if the client does not exit promptly.
            discoverySession.write("scan off\nquit\n")
            discoveryStopFallback.restart()
            state.discovering = false
            state.actionMessage = "Discovery stopped."
            clearStatus.restart()
            refreshSoon.restart()
            return true
        }

        // Never send Adapter1.StopDiscovery from a fresh one-shot D-Bus client:
        // that client owns no session and must not interfere with another app.
        state.discovering = false
        refreshSoon.restart()
        return true
    }

    function connectDevice(device) {
        if (!device || !device.path)
            return false
        return runAction(["connect", String(device.path)], "connect", String(device.path))
    }


    function disconnectDevice(device) {
        if (!device || !device.path)
            return false
        return runAction(["disconnect", String(device.path)], "disconnect", String(device.path))
    }

    function reconnectDevice(device) {
        if (!device || !device.path || !device.connected)
            return false
        return runAction(["reconnect", String(device.path)], "reconnect", String(device.path))
    }

    function clearPairingPrompt() {
        state.pairingPromptKind = ""
        state.pairingPromptValue = ""
        state.pairingPromptRequestId = 0
        state.pairingServiceUuid = ""
        state.pairingInputError = ""
    }

    function pairDevice(device) {
        if (!device || !device.path || actionProcess.running
                || pairingProcess.running)
            return false
        clearStatus.stop()
        state.errorText = ""
        state.actionMessage = "Waiting for pairing…"
        state.activeAction = "pair"
        state.activeDevicePath = String(device.path)
        state.pairingResultSeen = false
        state.pairingResultOk = false
        state.pairingResultMessage = ""
        state.pairingCancelRequested = false
        state.clearPairingPrompt()
        pairingProcess.exec([
            "python", backendPath(), "pair-session", String(device.path)
        ])
        return true
    }

    function respondPairing(accepted, value) {
        if (!pairingProcess.running || state.pairingPromptRequestId <= 0)
            return false
        pairingProcess.write(JSON.stringify({
            "action": accepted ? "accept" : "reject",
            "requestId": state.pairingPromptRequestId,
            "value": value || ""
        }) + "\n")
        return true
    }

    function cancelPairing(device) {
        if (!device || !device.path || cancelProcess.running)
            return false
        state.clearPairingPrompt()
        state.pairingCancelRequested = true
        if (pairingProcess.running) {
            pairingProcess.write(JSON.stringify({"action": "cancel-session"}) + "\n")
            pairingCancelFallback.restart()
            return true
        }
        // Device paths originate from BlueZ ObjectManager state, not user text.
        // This is only a bounded fallback if the interactive agent has already
        // exited before the UI's cancellation reaches it.
        cancelProcess.exec([
            "busctl", "--system", "call", "org.bluez", String(device.path),
            "org.bluez.Device1", "CancelPairing"
        ])
        return true
    }

    function forgetDevice(device) {
        if (!device || !device.path || adapterPath === "")
            return false
        return runAction(["forget", adapterPath, String(device.path)], "forget", String(device.path))
    }

    Process {
        id: snapshotProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.available = Boolean(payload.available)
                    state.bluetoothEnabled = Boolean(payload.enabled)
                    // Keep opening motion truthful while BlueZ's Discovering
                    // property catches up with the just-started owned session.
                    state.discovering = Boolean(payload.discovering) || discoverySession.running
                    state.adapterPath = String(payload.adapterPath || "")
                    state.pairedDevices = payload.paired || []
                    state.availableDevices = payload.availableDevices || []
                    state.connectedDevices = payload.connected || []
                    state.autoConnectEligible = payload.autoConnectEligible || []
                    state.errorText = String(payload.error || "")
                    state.snapshotReady = true
                    if (!state.available)
                        state.clearPairingPrompt()
                } catch (error) {
                    state.errorText = "Bluetooth status could not be read."
                    console.log("maho-link bluetooth snapshot parse:", error)
                }
            }
        }
    }

    Process {
        id: actionProcess

        stdout: StdioCollector {
            onStreamFinished: {
                const action = state.activeAction
                const devicePath = state.activeDevicePath
                try {
                    const payload = JSON.parse(this.text)
                    if (payload.ok) {
                        state.errorText = ""
                        state.actionMessage = String(payload.message || "")
                        if (state.actionMessage !== "")
                            clearStatus.restart()
                        state.actionSucceeded(action, devicePath)
                    } else {
                        clearStatus.stop()
                        state.actionMessage = ""
                        state.errorText = String(payload.message || "Bluetooth action failed.")
                        state.actionFailed(action, devicePath)
                    }
                } catch (error) {
                    clearStatus.stop()
                    state.actionMessage = ""
                    state.errorText = "Bluetooth action returned an invalid response."
                    state.actionFailed(action, devicePath)
                    console.log("maho-link bluetooth action parse:", error)
                }
                state.activeAction = ""
                state.activeDevicePath = ""
                refreshSoon.restart()
            }
        }
    }

    Process {
        id: pairingProcess
        stdinEnabled: true

        stdout: SplitParser {
            onRead: function(line) {
                let payload
                try {
                    payload = JSON.parse(line)
                } catch (error) {
                    state.pairingInputError = "Pairing helper returned an invalid response."
                    return
                }

                const type = String(payload.type || "")
                if (type === "ready") {
                    state.actionMessage = "Waiting for pairing…"
                    return
                }
                if (type === "prompt") {
                    state.pairingPromptKind = String(payload.kind || "")
                    state.pairingPromptValue = String(payload.value || "")
                    state.pairingPromptRequestId = Number(payload.requestId || 0)
                    state.pairingServiceUuid = String(payload.serviceUuid || "")
                    state.pairingInputError = ""
                    state.actionMessage = ""
                    return
                }
                if (type === "display") {
                    state.pairingPromptKind = "display-" + String(payload.kind || "")
                    state.pairingPromptValue = String(payload.value || "")
                    state.pairingPromptRequestId = 0
                    state.pairingServiceUuid = ""
                    state.pairingInputError = ""
                    return
                }
                if (type === "accepted") {
                    state.clearPairingPrompt()
                    state.actionMessage = "Waiting for BlueZ…"
                    return
                }
                if (type === "input-error") {
                    state.pairingInputError = String(payload.message || "Pairing input was invalid.")
                    return
                }
                if (type === "cancelled") {
                    state.clearPairingPrompt()
                    state.actionMessage = String(payload.message || "Pairing was cancelled.")
                    return
                }
                if (type === "status") {
                    state.actionMessage = String(payload.message || "")
                    return
                }
                if (type === "result") {
                    state.pairingResultSeen = true
                    state.pairingResultOk = Boolean(payload.ok)
                    state.pairingResultMessage = String(payload.message || "")
                    state.clearPairingPrompt()
                }
            }
        }

        onRunningChanged: {
            if (running || state.activeAction !== "pair")
                return

            pairingCancelFallback.stop()
            const devicePath = state.activeDevicePath
            const ok = state.pairingResultSeen && state.pairingResultOk
            const cancelled = state.pairingCancelRequested
            const message = state.pairingResultSeen
                ? state.pairingResultMessage
                : cancelled
                    ? "Pairing was cancelled."
                    : "Bluetooth pairing helper stopped unexpectedly."

            state.clearPairingPrompt()
            state.activeAction = ""
            state.activeDevicePath = ""
            state.pairingResultSeen = false
            state.pairingResultOk = false
            state.pairingResultMessage = ""
            state.pairingCancelRequested = false

            if (ok) {
                state.errorText = ""
                state.actionMessage = message || "Paired."
                clearStatus.restart()
                state.actionSucceeded("pair", devicePath)
            } else if (cancelled) {
                state.errorText = ""
                state.actionMessage = message || "Pairing was cancelled."
                clearStatus.restart()
                state.actionFailed("pair", devicePath)
            } else {
                clearStatus.stop()
                state.actionMessage = ""
                state.errorText = message || "Pairing failed."
                state.actionFailed("pair", devicePath)
            }
            refreshSoon.restart()
        }
    }


    Process {
        id: cancelProcess
        stdout: StdioCollector {
            onStreamFinished: refreshSoon.restart()
        }
    }

    // Persistent discovery-session owner. The stdin pipe deliberately remains
    // open until Maho stops the scan, the bounded scan expires, or this shell
    // closes. Quickshell owns and tears down the child process lifetime.
    Process {
        id: discoverySession
        command: [state.discoveryClientBinary]
        stdinEnabled: true

        onStarted: {
            discoverySession.write("scan on\n")
            discoveryStartVerify.restart()
        }

        onRunningChanged: {
            if (!running) {
                const elapsed = Date.now() - state.discoveryStartedAt
                const failedEarly = state.discoveryStartedAt > 0
                    && elapsed < 1600
                    && !state.discoveryStopping

                discoveryStopFallback.stop()
                discoverySessionTimeout.stop()
                state.discovering = false

                if (failedEarly)
                    state.errorText = "Bluetooth discovery could not stay active."

                state.discoveryStopping = false
                refreshSoon.restart()
            }
        }
    }

    // BlueZ PropertiesChanged / InterfacesAdded / InterfacesRemoved events are
    // the normal refresh authority. A slow timer below is only a reconnect
    // fallback for monitor restarts or session-resume edges.
    Process {
        id: bluezMonitor
        command: ["busctl", "--system", "monitor", "org.bluez"]
        running: true
        stdout: SplitParser {
            onRead: function(line) {
                if (String(line).indexOf("org.bluez") >= 0
                        || String(line).indexOf("PropertiesChanged") >= 0
                        || String(line).indexOf("InterfacesAdded") >= 0
                        || String(line).indexOf("InterfacesRemoved") >= 0)
                    monitorDebounce.restart()
            }
        }
    }

    Timer {
        id: monitorDebounce
        interval: 140
        onTriggered: state.refresh()
    }

    Timer {
        id: refreshSoon
        interval: 260
        onTriggered: state.refresh()
    }


    Timer {
        id: pairingCancelFallback
        interval: 900
        onTriggered: {
            if (!pairingProcess.running)
                return
            const devicePath = state.activeDevicePath
            if (devicePath !== "" && !cancelProcess.running) {
                cancelProcess.exec([
                    "busctl", "--system", "call", "org.bluez", devicePath,
                    "org.bluez.Device1", "CancelPairing"
                ])
            }
            state.pairingResultSeen = true
            state.pairingResultOk = false
            state.pairingResultMessage = "Pairing was cancelled."
            pairingProcess.running = false
        }
    }

    Timer {
        id: discoveryStartVerify
        interval: 650
        onTriggered: state.refresh()
    }

    // Discovery is intentionally bounded. Twenty seconds is long enough for
    // normal LE/BR-EDR discovery while avoiding a forgotten continuous scan.
    Timer {
        id: discoverySessionTimeout
        interval: 20000
        onTriggered: state.stopDiscovery()
    }

    Timer {
        id: discoveryStopFallback
        interval: 700
        onTriggered: {
            if (discoverySession.running)
                discoverySession.running = false
        }
    }

    // InterfacesAdded signals remain the fast path. While Maho owns the scan,
    // also sample ObjectManager at a short bounded cadence so adapters/drivers
    // that delay monitor output still surface devices within about one second.
    Timer {
        id: discoveryRefresh
        interval: 900
        repeat: true
        running: discoverySession.running
        onTriggered: state.refresh()
    }

    Timer {
        id: clearStatus
        interval: 1700
        onTriggered: {
            if (state.errorText === "")
                state.actionMessage = ""
        }
    }

    Timer {
        interval: 12000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: state.refresh()
    }
}
