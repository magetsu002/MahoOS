import QtQuick
import Quickshell
import Quickshell.Services.Mpris

Scope {
    id: media

    // Prefer the player that is actively playing. If none are playing, keep the
    // first exposed player so paused media remains controllable without waiting
    // for a polling loop or an external playerctl process.
    readonly property var player: {
        const players = Mpris.players.values

        for (let i = 0; i < players.length; ++i) {
            if (players[i].isPlaying)
                return players[i]
        }

        return players.length > 0 ? players[0] : null
    }

    readonly property bool available: player !== null
    readonly property bool playing: available && player.isPlaying
    readonly property string title: available ? (player.trackTitle || "") : ""
    readonly property string artist: available ? (player.trackArtist || "") : ""
    readonly property string artUrl: available ? (player.trackArtUrl || "") : ""
    readonly property string identity: available ? (player.identity || "") : ""

    readonly property bool canPrevious: available && player.canGoPrevious
    readonly property bool canNext: available && player.canGoNext
    readonly property bool canToggle: available && player.canTogglePlaying

    function previous() {
        if (canPrevious)
            player.previous()
    }

    function next() {
        if (canNext)
            player.next()
    }

    function toggle() {
        if (canToggle)
            player.togglePlaying()
    }
}
