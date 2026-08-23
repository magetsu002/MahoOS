import QtQuick
import Quickshell.Bluetooth

Scope {
    id: bluetooth

    readonly property var adapter: Bluetooth.defaultAdapter
    readonly property bool available: adapter !== null
    readonly property bool enabled: available && adapter.enabled

    readonly property var connectedDevices: {
        if (!adapter)
            return []

        const devices = adapter.devices.values
        const result = []

        for (let i = 0; i < devices.length; ++i) {
            if (devices[i].connected)
                result.push(devices[i])
        }

        return result
    }

    readonly property bool connected: connectedDevices.length > 0
    readonly property string connectedName: connected
        ? (connectedDevices[0].name || connectedDevices[0].address || "Connected")
        : ""

    function toggleEnabled() {
        if (adapter)
            adapter.enabled = !adapter.enabled
    }
}
