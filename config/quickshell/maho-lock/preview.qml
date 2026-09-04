//@ pragma ShellId maho-lock-preview

import QtQuick
import Quickshell
import Quickshell.Wayland

ShellRoot {
    id: root

    MahoLockTheme {
        id: theme
    }

    MahoLockState {
        id: state
    }

    QtObject {
        id: previewAuth

        property bool authenticating: false
        property bool unlocking: false
        property string errorText: ""

        signal failed()
        signal succeeded()

        function submit(secret) {
            if (String(secret || "").length === 0)
                return
            errorText = "Preview only — PAM is not invoked"
            failed()
        }
    }

    PanelWindow {
        id: previewWindow

        anchors {
            top: true
            bottom: true
            left: true
            right: true
        }

        color: theme.background
        aboveWindows: true
        focusable: true
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "maho-lock-preview"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

        MahoLockViewV2 {
            anchors.fill: parent
            theme: theme
            state: state
            auth: previewAuth
            previewMode: true
        }
    }
}
