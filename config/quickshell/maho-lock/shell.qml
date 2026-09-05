//@ pragma ShellId maho-lock

import QtQuick
import Quickshell
import Quickshell.Wayland

ShellRoot {
    id: root

    property bool wasSecure: false

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
            if (secure) {
                root.wasSecure = true
            } else if (root.wasSecure && !locked) {
                // Successful release has completed. This locker is one-shot;
                // leave no dormant Quickshell instance behind.
                Qt.quit()
            }
        }

        Component.onCompleted: locked = true
    }
}
