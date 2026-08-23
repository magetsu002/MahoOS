import QtQuick
import Quickshell
import Quickshell.Services.UPower

Scope {
    id: battery

    readonly property var device: UPower.displayDevice
    readonly property bool available: device !== null && device.ready

    // Quickshell intentionally normalizes UPower percentages to the 0..1
    // range. Keep the public Maho Shell contract in human percent (0..100).
    readonly property int percentage: available
        ? Math.max(0, Math.min(100, Math.round(device.percentage * 100)))
        : 100

    readonly property bool charging: available && (
        device.state === UPowerDeviceState.Charging
        || device.state === UPowerDeviceState.PendingCharge
        || device.state === UPowerDeviceState.FullyCharged
    )

    readonly property bool full: available
        && device.state === UPowerDeviceState.FullyCharged

    readonly property bool onBattery: UPower.onBattery
    readonly property real health: available && device.healthSupported
        ? device.healthPercentage * 100
        : -1
    readonly property real timeToEmpty: available ? device.timeToEmpty : 0
    readonly property real timeToFull: available ? device.timeToFull : 0
}
