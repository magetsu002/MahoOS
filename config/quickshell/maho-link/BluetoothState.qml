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
        return runAction(["toggle", adapterPath, enabled ? "on" : "off"], "toggle", "")
    }

    function startDiscovery() {
        if (adapterPath === "" || !bluetoothEnabled)
            return false
        return runAction(["scan-start", adapterPath], "scan-start", "")
    }

    function stopDiscovery() {
        if (adapterPath === "")
            return false
        return runAction(["scan-stop", adapterPath], "scan-stop", "")
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
                    state.discovering = Boolean(payload.discovering)
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
