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
    property string errorText: ""
    property string actionMessage: ""
    property string activeAction: ""
    property string activeDevicePath: ""
    property bool snapshotReady: false
    property bool discoveryStopping: false
    property real discoveryStartedAt: 0
    readonly property bool discoveryOwned: discoverySession.running
    readonly property bool busy: snapshotProcess.running || actionProcess.running || cancelProcess.running

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
        if (actionProcess.running)
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

    // BlueZ discovery is a per-D-Bus-client session. A one-shot `busctl call`
    // returns success but immediately drops the client that acquired the
    // discovery session, which lets BlueZ stop scanning again. Keep one
    // bluetoothctl process alive solely as the session owner. Device identity,
    // metadata and results still come only from the structured ObjectManager
    // snapshot below; bluetoothctl output is never used as data authority.
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
            // Ask bluetoothctl to release its own session before quitting. The
            // fallback timer below terminates it if the command does not exit.
            discoverySession.write("scan off\nquit\n")
            discoveryStopFallback.restart()
            state.discovering = false
            state.actionMessage = "Discovery stopped."
            clearStatus.restart()
            refreshSoon.restart()
            return true
        }

        // Never call Adapter1.StopDiscovery from a fresh one-shot D-Bus client:
        // that client does not own the session and must not interfere with a
        // discovery session held by another application.
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

    function pairDevice(device) {
        if (!device || !device.path)
            return false
        return runAction(["pair", String(device.path)], "pair", String(device.path))
    }

    function cancelPairing(device) {
        if (!device || !device.path || cancelProcess.running)
            return false
        // Device paths originate from BlueZ ObjectManager state, not user text.
        // Pass them as a distinct argv item; never interpolate device names.
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
                    // If Maho owns a discovery session, keep the UI in the
                    // discovering state during the few milliseconds before
                    // BlueZ's Discovering property catches up.
                    state.discovering = Boolean(payload.discovering) || discoverySession.running
                    state.adapterPath = String(payload.adapterPath || "")
                    state.pairedDevices = payload.paired || []
                    state.availableDevices = payload.availableDevices || []
                    state.connectedDevices = payload.connected || []
                    state.errorText = String(payload.error || "")
                    state.snapshotReady = true
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
        id: cancelProcess
        stdout: StdioCollector {
            onStreamFinished: refreshSoon.restart()
        }
    }

    // Persistent BlueZ discovery-session owner. The stdin pipe deliberately
    // stays open until Maho stops discovery, the 20-second bounded scan expires,
    // or the Maho Link shell closes. Quickshell owns the child process lifetime.
    Process {
        id: discoverySession
        command: ["bluetoothctl"]
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
        id: discoveryStartVerify
        interval: 650
        onTriggered: state.refresh()
    }

    // Discovery is intentionally bounded. Twenty seconds is long enough for
    // normal LE/BR-EDR discovery while avoiding a forgotten battery-draining
    // scan if the panel is left open.
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
