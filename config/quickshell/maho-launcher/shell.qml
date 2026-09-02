//@ pragma ShellId maho-launcher

import Quickshell
import Quickshell.Io

ShellRoot {
    id: root

    MahoLauncherWindow {
        id: launcher
    }

    IpcHandler {
        target: "launcher"

        function close(): bool {
            launcher.closeLauncher()
            return true
        }

        function focus(): bool {
            launcher.focusSearch()
            return true
        }
    }
}
