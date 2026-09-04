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
    readonly property real batteryFraction: {
        if (!batteryAvailable)
            return -1
        const raw = Number(batteryDevice.percentage)
        if (!Number.isFinite(raw))
            return -1
        return Math.max(0, Math.min(1, raw))
    }
    readonly property bool batteryPercentageValid: batteryFraction >= 0
    readonly property int batteryPercentage: batteryPercentageValid
        ? Math.round(batteryFraction * 100)
        : 0
    readonly property bool batteryCharging: batteryAvailable && (
        batteryDevice.state === UPowerDeviceState.Charging
        || batteryDevice.state === UPowerDeviceState.PendingCharge
        || batteryDevice.state === UPowerDeviceState.FullyCharged
    )

    // Current desktop wallpaper remains observable for future user-selectable
    // lock wallpaper policy, but Maho Lock v1 deliberately uses a dedicated,
    // pre-softened lock background for deterministic fidelity.
    readonly property string activeWallpaperKind: wallpaper.kind || ""
    readonly property string activeWallpaperPath: wallpaper.path || ""
    readonly property bool activeWallpaperIsImage:
        activeWallpaperKind === "image" && activeWallpaperPath.length > 0
    readonly property string activeWallpaperUrl:
        activeWallpaperIsImage
            ? encodeURI("file://" + activeWallpaperPath)
            : ""

    readonly property string lockWallpaperUrl:
        encodeURI("file://" + Quickshell.shellPath("assets/maho-lock-dusk.jpg"))

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
