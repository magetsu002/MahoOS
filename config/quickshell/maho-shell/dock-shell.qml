//@ pragma ShellId maho-dock

import QtQuick
import Quickshell
import Quickshell.Hyprland

ShellRoot {
    id: root

    MahoTheme {
        id: theme
    }

    MahoDockState {
        id: appDockState
    }

    MahoDockModel {
        id: appDockModel
        dockState: appDockState
    }

    MahoDock {
        id: dock
        theme: theme
        dockModel: appDockModel
        dockState: appDockState

        // Desktop presence rule: the Dock rests fully open only when there is
        // no active application toplevel. Any active app window retracts it to
        // the tiny shelf, regardless of whether Hyprland classifies that window
        // as tiled, maximized, fullscreen, or floating. Intentional pointer
        // approach and an open preview still temporarily reveal the full Dock.
        dockRevealProgress: {
            const top = Hyprland.activeToplevel
            const hasActiveAppWindow = Boolean(top && top.activated)
            const shouldRetreat = hasActiveAppWindow
                && !dock.pointerInsideMaterial
                && !dock.previewOpen
                && dock.previewProgress < 0.02
            return shouldRetreat ? 0 : 1
        }
    }
}
