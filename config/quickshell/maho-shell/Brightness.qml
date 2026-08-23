import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: brightness

    property int value: -1
    property bool available: false
    property bool initialized: false
    property bool overlayOpen: false
    property bool commandAvailable: false

    function parse(text) {
        const match = String(text || "").match(/(\d+)%/)
        if (!match) {
            available = false
            return
        }

        const next = Math.max(0, Math.min(100, Number(match[1])))
        const changed = initialized && next !== value

        commandAvailable = true
        available = true
        value = next
        initialized = true

        if (changed)
            showOverlay()
    }

    function showOverlay() {
        overlayOpen = true
        overlayTimer.restart()
    }

    function setValue(percent) {
        if (!available || !commandAvailable)
            return

        const bounded = Math.max(1, Math.min(100, Math.round(percent)))
        value = bounded
        initialized = true
        showOverlay()

        Quickshell.execDetached([
            "brightnessctl",
            "set",
            bounded + "%"
        ])
    }

    Process {
        id: probe
        command: [
            "bash",
            "-lc",
            "command -v brightnessctl >/dev/null 2>&1 && brightnessctl -m"
        ]
        running: true
        stdout: StdioCollector {
            onStreamFinished: brightness.parse(this.text)
        }
    }

    Process {
        id: reader
        stdout: StdioCollector {
            onStreamFinished: brightness.parse(this.text)
        }
    }

    Timer {
        interval: 250
        repeat: true
        running: brightness.commandAvailable
        onTriggered: {
            if (!reader.running)
                reader.exec(["brightnessctl", "-m"])
        }
    }

    Timer {
        id: overlayTimer
        interval: 1450
        onTriggered: brightness.overlayOpen = false
    }
}
