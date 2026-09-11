//@ pragma ShellId maho-dock-state-probe

import QtQuick
import Quickshell

ShellRoot {
    MahoDockState {
        id: dockState
    }

    Timer {
        interval: 250
        running: true
        repeat: false
        onTriggered: {
            const requestedPin = String(Quickshell.env("MAHO_DOCK_PROBE_PIN") || "").trim()
            if (requestedPin.length > 0)
                dockState.pin(requestedPin)
            console.log("MAHO_DOCK_PROBE_PINS=" + JSON.stringify(dockState.pins))
            exitTimer.start()
        }
    }

    Timer {
        id: exitTimer
        interval: 250
        repeat: false
        onTriggered: Qt.quit()
    }
}
