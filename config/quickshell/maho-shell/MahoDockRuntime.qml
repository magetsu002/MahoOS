import QtQuick
import Quickshell

Scope {
    id: root

    required property var theme

    MahoDockState {
        id: appDockState
    }

    MahoDockModel {
        id: appDockModel
        dockState: appDockState
    }

    MahoDock {
        theme: root.theme
        dockModel: appDockModel
        dockState: appDockState
    }
}
