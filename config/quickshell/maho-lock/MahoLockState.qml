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
    property string selectedLockWallpaperPath: ""

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

    readonly property string activeWallpaperKind: wallpaper.kind || ""
    readonly property string activeWallpaperPath: wallpaper.path || ""
    readonly property bool activeWallpaperIsImage:
        activeWallpaperKind === "image" && activeWallpaperPath.length > 0

    readonly property string fallbackLockWallpaperPath:
        Quickshell.shellPath("assets/maho-lock-dusk.jpg")

    readonly property string lockWallpaperPath:
        selectedLockWallpaperPath.length > 0
            ? selectedLockWallpaperPath
            : (activeWallpaperIsImage
                ? activeWallpaperPath
                : fallbackLockWallpaperPath)

    readonly property string lockWallpaperUrl:
        lockWallpaperPath.length > 0
            ? encodeURI("file://" + lockWallpaperPath)
            : ""

    function refreshAmbientState() {
        if (!probe.running)
            probe.exec(["python", Quickshell.shellPath("state.py")])
    }

    function chooseLockWallpaper() {
        if (!wallpaperPicker.running)
            wallpaperPicker.exec([
                "python",
                Quickshell.shellPath("state.py"),
                "--pick-wallpaper"
            ])
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
                    // Optional ambient probes must never block locking.
                }
            }
        }
    }

    Process {
        id: wallpaperPicker

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    const path = String(payload.path || "")
                    if (path.length > 0)
                        state.selectedLockWallpaperPath = path
                } catch (error) {
                    // Fall back to the current desktop or bundled lock image.
                }
            }
        }
    }

    Process { id: suspendProcess }
    Process { id: switchUserProcess }

    Timer {
        interval: 1
        repeat: false
        running: true
        onTriggered: state.chooseLockWallpaper()
    }

    Timer {
        interval: 2000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: state.refreshAmbientState()
    }
}
