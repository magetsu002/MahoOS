import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: theme

    function palette(name, fallback) {
        const colors = data.colors
        if (colors && colors[name] !== undefined && colors[name] !== null)
            return colors[name]
        return fallback
    }

    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }

    property color surface: palette("surface", "#151318")
    property color surfaceLow: palette("surface_container_low", "#211f24")
    property color surfaceHigh: palette("surface_container_high", "#2b2930")
    property color surfaceHighest: palette("surface_container_highest", "#36343a")
    property color foreground: palette("foreground", "#e6e1e5")
    property color muted: palette("muted", "#cac4d0")
    property color outline: palette("outline", "#938f99")
    property color primary: palette("primary", "#d0bcff")
    property color secondary: palette("secondary", "#ccc2dc")
    property color tertiary: palette("tertiary", "#efb8c8")
    property color error: palette("error", "#f2b8b5")

    FileView {
        path: Quickshell.env("HOME") + "/.cache/maho/theme/active.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: reload()

        JsonAdapter {
            id: data
            property int version: 0
            property var colors: ({})
            property string mode: "dark"
            property var source: ({})
        }
    }
}
