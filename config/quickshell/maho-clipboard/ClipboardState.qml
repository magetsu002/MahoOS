import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: state

    property bool available: false
    property bool loading: false
    property bool mutating: false
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

    function togglePin(item) {
        if (mutationProcess.running || !item)
            return false
        const pinned = Boolean(item.pinned)
        const target = pinned ? String(item.pinKey || "") : String(item.id || "")
        if (target.length === 0)
            return false
        mutating = true
        errorText = ""
        mutationProcess.exec([
            "python",
            backendPath(),
            pinned ? "unpin" : "pin",
            target,
        ])
        return true
    }

    function clearUnpinned() {
        if (mutationProcess.running)
            return false
        mutating = true
        errorText = ""
        mutationProcess.exec(["python", backendPath(), "clear"])
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

    Process {
        id: mutationProcess
        stdout: StdioCollector {
            onStreamFinished: {
                state.mutating = false
                try {
                    const payload = JSON.parse(this.text)
                    if (payload.ok) {
                        state.errorText = ""
                        state.refresh()
                    } else {
                        state.errorText = String(payload.error || "Clipboard history could not be updated.")
                    }
                } catch (error) {
                    state.errorText = "Clipboard history could not be updated."
                    console.log("maho-clipboard mutation parse failed")
                }
            }
        }
    }
}
