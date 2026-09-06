import QtQuick
import Quickshell
import Quickshell.Io

// Maho Shell is the session-lifetime owner for Bluetooth auto-connect policy.
// The policy command performs one authoritative BlueZ snapshot and one bounded
// action at most; this component only supplies lifecycle and event triggers.
Scope {
    id: policy

    readonly property string launcher:
        Quickshell.env("HOME") + "/.local/bin/maho-link"

    function evaluate() {
        if (!runner.running)
            runner.exec([policy.launcher, "auto-connect-policy"])
    }

    Process {
        id: runner

        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    if (String(payload.status || "") === "backoff") {
                        const seconds = Math.max(1, Number(payload.retryAfter || 5))
                        retry.interval = Math.min(120000, seconds * 1000)
                        retry.restart()
                    }
                } catch (error) {
                    // A missing adapter or command is non-fatal to Maho Shell;
                    // the bounded periodic check will try again later.
                }
            }
        }
    }

    // BlueZ signals make adapter power, device reachability, and connection
    // transitions prompt. The backend still re-reads ObjectManager state before
    // every action, so monitor text is never interpreted as device truth.
    Process {
        id: bluezMonitor
        command: ["busctl", "--system", "monitor", "org.bluez"]
        running: true

        stdout: SplitParser {
            onRead: bluezDebounce.restart()
        }
    }

    Timer {
        id: bluezDebounce
        interval: 300
        onTriggered: policy.evaluate()
    }

    Timer {
        id: retry
        onTriggered: policy.evaluate()
    }

    // A bounded fallback covers BlueZ restarts and monitor unavailability.
    Timer {
        interval: 12000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: policy.evaluate()
    }
}
