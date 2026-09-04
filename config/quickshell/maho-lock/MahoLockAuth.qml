import QtQuick
import Quickshell
import Quickshell.Services.Pam

Scope {
    id: auth

    required property var lock

    property bool unlocking: false
    property string pendingSecret: ""
    property string errorText: ""
    readonly property bool authenticating: pam.active

    signal failed()
    signal succeeded()

    function submit(secret) {
        if (unlocking || pam.active)
            return

        const value = String(secret || "")
        if (value.length === 0)
            return

        pendingSecret = value
        errorText = ""

        if (!pam.start()) {
            pendingSecret = ""
            errorText = "Authentication unavailable"
            failed()
        }
    }

    PamContext {
        id: pam
        config: "login"

        onPamMessage: {
            if (responseRequired) {
                pam.respond(auth.pendingSecret)
            } else if (messageIsError && message.length > 0) {
                auth.errorText = message
            }
        }

        onCompleted: function(result) {
            auth.pendingSecret = ""

            if (result === PamResult.Success) {
                auth.errorText = ""
                auth.unlocking = true
                auth.succeeded()
                releaseTimer.start()
                return
            }

            auth.errorText = result === PamResult.MaxTries
                ? "Too many attempts"
                : "Incorrect password"
            auth.failed()
        }

        onError: function(error) {
            auth.pendingSecret = ""
            auth.errorText = "Authentication error"
        }
    }

    Timer {
        id: releaseTimer
        interval: 240
        repeat: false
        onTriggered: {
            // The session is released only after PAM explicitly succeeded.
            auth.lock.locked = false
        }
    }
}
