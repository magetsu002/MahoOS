pragma ComponentBehavior: Bound

//@ pragma ShellId maho-lock

import QtQuick
import Quickshell
import Quickshell.Wayland
import Quickshell.Io

ShellRoot {
    id: root

    property bool wasSecure: false

    function quitAfterSecureRelease() {
        if (wasSecure && !sessionLock.secure && !sessionLock.locked) {
            console.info("maho-lock lifecycle: secure release complete; exiting")
            Qt.quit()
        }
    }

    MahoLockTheme {
        id: theme
    }

    MahoLockState {
        id: lockState
    }

    MahoLockAuth {
        id: auth
        lock: sessionLock
    }

    IpcHandler {
        target: "sessionEvidence"
        function lockProof(): string {
            return JSON.stringify({secure: sessionLock.secure, locked: sessionLock.locked})
        }
    }

    WlSessionLock {
        id: sessionLock

        MahoLockSurface {
            theme: theme
            lockState: lockState
            auth: auth
            secure: sessionLock.secure
        }

        onSecureChanged: {
            console.info("maho-lock lifecycle: session secure=" + secure
                + "; locked=" + locked)
            if (secure)
                root.wasSecure = true

            root.quitAfterSecureRelease()
        }

        onLockedChanged: {
            console.info("maho-lock lifecycle: session locked=" + locked
                + "; secure=" + secure)
            // secure and locked can fall in either order. Exit only after both
            // confirm that the successfully authenticated release is complete.
            root.quitAfterSecureRelease()
        }

        Component.onCompleted: locked = true
    }
}
