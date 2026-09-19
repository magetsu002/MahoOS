//@ pragma ShellId maho-launcher

import Quickshell
import Quickshell.Io

ShellRoot {
    id: root
    readonly property string runtimeIdentity: Quickshell.env("MAHO_RUNTIME_IDENTITY")

    LauncherBackdrop {
        active: launcher.shown && !launcher.closing
        onDismissRequested: launcher.closeLauncher()
    }

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

        function runtimeIdentity(): string { return root.runtimeIdentity }
    }
}
