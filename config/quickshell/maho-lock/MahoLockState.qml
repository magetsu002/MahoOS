import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Services.UPower

Scope {
    id: state

    function stateHome() {
        const configured = Quickshell.env("XDG_STATE_HOME")
        return configured && String(configured).length > 0
            ? String(configured)
            : Quickshell.env("HOME") + "/.local/state"
    }

    property string userName: String(Quickshell.env("USER") || "")
    property string displayName: {
        const source = userName.replace(/[-_]+/g, " ").trim()
        if (source.length === 0)
            return "User"
        return source.charAt(0).toUpperCase() + source.slice(1)
    }
    property string networkKind: "none"
    property string keyboardLayout: "US"
    property var switchUserCommand: []

    readonly property var batteryDevice: UPower.displayDevice
    readonly property bool batteryAvailable:
        batteryDevice !== null && batteryDevice.ready
    readonly property int batteryPercentage: batteryAvailable
        ? Math.max(0, Math.min(100, Math.round(batteryDevice.percentage * 100)))
        : 100
    readonly property bool batteryCharging: batteryAvailable && (
        batteryDevice.state === UPowerDeviceState.Charging
        || batteryDevice.state === UPowerDeviceState.PendingCharge
        || batteryDevice.state === UPowerDeviceState.FullyCharged
    )

    readonly property string wallpaperKind: wallpaper.kind || ""
    readonly property string wallpaperPath: wallpaper.path || ""
    readonly property bool wallpaperIsImage:
        wallpaperKind === "image" && wallpaperPath.length > 0
    readonly property string wallpaperUrl:
        wallpaperIsImage ? encodeURI("file://" + wallpaperPath) : ""

    function refreshAmbientState() {
        if (!probe.running)
            probe.exec(["python", Quickshell.shellPath("state.py")])
    }

    function suspend() {
        if (!suspendProcess.running)
            suspendProcess.exec(["systemctl", "suspend"])
    }

    function switchUser() {
        if (switchUserCommand.length > 0 && !switchUserProcess.running)
            switchUserProcess.exec(switchUserCommand)
    }

    FileView {
        path: state.stateHome() + "/maho/wallpaper/current.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: reload()

        JsonAdapter {
            id: wallpaper
            property int version: 0
            property string provider: ""
            property string kind: ""
            property string path: ""
        }
    }

    Process {
        id: probe

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.userName = String(payload.userName || state.userName)
                    state.displayName = String(payload.displayName || state.displayName)
                    state.networkKind = String(payload.networkKind || "none")
                    state.keyboardLayout = String(payload.keyboardLayout || "US")
                    state.switchUserCommand = payload.switchUserCommand || []
                } catch (error) {
                    // Keep the last known ambient state. Locking must never
                    // depend on optional network/layout probes succeeding.
                }
            }
        }
    }

    Process { id: suspendProcess }
    Process { id: switchUserProcess }

    Timer {
        interval: 2000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: state.refreshAmbientState()
    }
}
