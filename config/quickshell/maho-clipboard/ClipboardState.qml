import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property bool available: false
    property bool loading: false
    property var items: []
    property string errorText: ""
    signal selectionCopied()

    function backendPath() {
        return Quickshell.shellPath("clipboard.py")
    }

    function refresh() {
        if (listProcess.running)
            return
        loading = true
        errorText = ""
        listProcess.exec(["python", backendPath(), "list"])
    }

    function selectItem(itemId) {
        if (selectProcess.running || !itemId)
            return false
        errorText = ""
        selectProcess.exec(["python", backendPath(), "select", String(itemId)])
        return true
    }

    Process {
        id: listProcess
        stdout: StdioCollector {
            onStreamFinished: {
                state.loading = false
                try {
                    const payload = JSON.parse(this.text)
                    state.available = Boolean(payload.available)
                    state.items = payload.items || []
                    state.errorText = String(payload.error || "")
                } catch (error) {
                    state.available = false
                    state.items = []
                    state.errorText = "Clipboard history could not be read."
                    console.log("maho-clipboard list parse failed")
                }
            }
        }
    }

    Process {
        id: selectProcess
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const payload = JSON.parse(this.text)
                    if (payload.ok) {
                        state.errorText = ""
                        state.selectionCopied()
                    } else {
                        state.errorText = String(payload.error || "Clipboard item could not be restored.")
                    }
                } catch (error) {
                    state.errorText = "Clipboard item could not be restored."
                    console.log("maho-clipboard selection parse failed")
                }
            }
        }
    }
}
