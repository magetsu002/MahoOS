//@ pragma ShellId maho-launcher

import Quickshell
import Quickshell.Io

ShellRoot {
    id: root
    readonly property string runtimeIdentity: Quickshell.env("MAHO_RUNTIME_IDENTITY")

    // Separate non-interactive compositor plane. It ignores other shell
    // exclusion zones and sits below Overlay-layer Maho Edge, so launcher blur
    // reaches the physical screen edge without blurring the Edge surface.
    LauncherBackdrop {
        id: backdrop
        active: launcher.presented
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
            launcher.openLauncher()
            return true
        }

        function runtimeIdentity(): string { return root.runtimeIdentity }
    }
}
