//@ pragma ShellId maho-dock

import QtQuick
import Quickshell

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
        theme: theme
        dockModel: appDockModel
        dockState: appDockState
    }
}
