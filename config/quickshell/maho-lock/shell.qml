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
        id: state
    }

    MahoLockAuth {
        id: auth
        lock: sessionLock
    }

    WlSessionLock {
        id: sessionLock

        MahoLockSurface {
            theme: theme
            state: state
            auth: auth
        }

        onSecureChanged: {
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
