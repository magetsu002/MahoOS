import QtQuick
import Quickshell
import Quickshell.Services.Pipewire

Scope {
    id: audio

    PwObjectTracker { objects: [Pipewire.defaultAudioSink] }

    readonly property var sink: Pipewire.defaultAudioSink

    property int volume: 0
    property bool muted: false
    property bool initialized: false
    property bool overlayOpen: false

    property var watcher: Connections {
        target: audio.sink ? audio.sink.audio : null
        function onVolumesChanged() { audio.syncFromPipewire() }
        function onMutedChanged() { audio.syncFromPipewire() }
    }

    onSinkChanged: syncFromPipewire()

    function syncFromPipewire() {
        if (!sink || !sink.audio)
            return

        const nextVolume = Math.round(sink.audio.volume * 100)
        const nextMuted = !!sink.audio.muted
        const changed = initialized
            && (nextVolume !== volume || nextMuted !== muted)

        volume = nextVolume
        muted = nextMuted
        initialized = true

        if (changed)
            showOverlay()
    }

    function showOverlay() {
        overlayOpen = true
        overlayTimer.restart()
    }

    function setVolume(percent) {
        const bounded = Math.max(0, Math.min(100, Math.round(percent)))

        if (sink && sink.audio) {
            sink.audio.volume = bounded / 100
            sink.audio.muted = false
        }

        volume = bounded
        muted = false
        initialized = true
        showOverlay()
    }

    function toggleMute() {
        if (sink && sink.audio)
            sink.audio.muted = !sink.audio.muted
        showOverlay()
    }

    Timer {
        id: overlayTimer
        interval: 1450
        onTriggered: audio.overlayOpen = false
    }

    Component.onCompleted: syncFromPipewire()
}
