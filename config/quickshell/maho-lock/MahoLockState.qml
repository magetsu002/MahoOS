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
    property string networkName: ""
    property string keyboardLayout: "US"
    property var switchUserCommand: []
    property string selectedLockWallpaperPath: ""
    property string avatarPath: ""
    property var avatarCandidates: []
    property string browserPath: ""
    property string browserParent: ""
    property var browserEntries: []

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
    )
    readonly property bool batteryFull: batteryAvailable && (
        batteryDevice.state === UPowerDeviceState.FullyCharged
        || batteryFraction >= 0.995
    )
    readonly property string batteryStatusText: {
        if (!batteryPercentageValid)
            return "Battery status unavailable"
        if (batteryFull)
            return batteryPercentage + "% · Fully charged"
        if (batteryCharging)
            return batteryPercentage + "% · Charging"
        return batteryPercentage + "% · On battery"
    }

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

    readonly property string avatarUrl:
        avatarPath.length > 0 ? encodeURI("file://" + avatarPath) : ""

    function refreshAmbientState() {
        if (!probe.running)
            probe.exec(["python", Quickshell.shellPath("state.py")])
    }

    function chooseLockWallpaper() {
        if (!wallpaperPicker.running)
            wallpaperPicker.exec(["python", Quickshell.shellPath("state.py"), "--pick-wallpaper"])
    }

    function shuffleLockWallpaper() {
        if (!wallpaperPicker.running)
            wallpaperPicker.exec(["python", Quickshell.shellPath("state.py"), "--shuffle-wallpaper"])
    }

    function setLockWallpaper(path) {
        if (!wallpaperWriteProcess.running) {
            wallpaperWriteProcess.exec([
                "python",
                Quickshell.shellPath("state.py"),
                "--set-wallpaper",
                String(path),
            ])
        }
    }

    function refreshAvatarCandidates() {
        if (!avatarListProcess.running)
            avatarListProcess.exec(["python", Quickshell.shellPath("state.py"), "--avatar-candidates"])
    }

    function setAvatar(path) {
        if (!avatarWriteProcess.running)
            avatarWriteProcess.exec(["python", Quickshell.shellPath("state.py"), "--set-avatar", String(path)])
    }

    function clearAvatar() {
        if (!avatarWriteProcess.running)
            avatarWriteProcess.exec(["python", Quickshell.shellPath("state.py"), "--clear-avatar"])
    }

    function browseImages(path) {
        if (!imageBrowserProcess.running) {
            const target = String(path || "")
            const args = ["python", Quickshell.shellPath("image_browser.py")]
            if (target.length > 0)
                args.push(target)
            imageBrowserProcess.exec(args)
        }
    }

    function switchKeyboardLayout() {
        if (!layoutSwitchProcess.running)
            layoutSwitchProcess.exec(["python", Quickshell.shellPath("state.py"), "--switch-layout"])
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
                    state.networkName = String(payload.networkName || "")
                    state.keyboardLayout = String(payload.keyboardLayout || "US")
                    state.switchUserCommand = payload.switchUserCommand || []
                    state.avatarPath = String(payload.avatarPath || "")
                    const savedWallpaper = String(payload.savedWallpaperPath || "")
                    if (savedWallpaper.length > 0 && state.selectedLockWallpaperPath.length === 0)
                        state.selectedLockWallpaperPath = savedWallpaper
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
                    // Fall back to current desktop or bundled lock image.
                }
            }
        }
    }

    Process {
        id: wallpaperWriteProcess

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    const path = String(payload.path || "")
                    if (payload.ok === true && path.length > 0)
                        state.selectedLockWallpaperPath = path
                } catch (error) {
                    // Keep the current wallpaper if selection persistence fails.
                }
            }
        }
    }

    Process {
        id: avatarListProcess

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.avatarCandidates = payload.paths || []
                } catch (error) {
                    state.avatarCandidates = []
                }
            }
        }
    }

    Process {
        id: avatarWriteProcess

        stdout: StdioCollector {
            onStreamFinished: state.refreshAmbientState()
        }
    }

    Process {
        id: imageBrowserProcess

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.browserPath = String(payload.path || "")
                    state.browserParent = String(payload.parent || "")
                    state.browserEntries = payload.entries || []
                } catch (error) {
                    state.browserPath = ""
                    state.browserParent = ""
                    state.browserEntries = []
                }
            }
        }
    }

    Process {
        id: layoutSwitchProcess

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    state.keyboardLayout = String(payload.keyboardLayout || state.keyboardLayout)
                } catch (error) {
                    state.refreshAmbientState()
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
