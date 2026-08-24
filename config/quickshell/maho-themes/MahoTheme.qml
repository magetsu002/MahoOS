import QtQuick
import Quickshell
import Quickshell.Io

Item {
    id: root

    function palette(name, fallback) {
        const colors = data.colors
        if (colors && colors[name] !== undefined && colors[name] !== null)
            return colors[name]
        return fallback
    }

    function role(name, fallback) {
        const semantic = data.semantic
        if (semantic && semantic[name] !== undefined && semantic[name] !== null)
            return semantic[name]
        return fallback
    }

    property color base: palette("surface", "#151318")
    property color mantle: palette("surface_container", "#211f24")
    property color crust: palette("background", "#101014")
    property color text: palette("foreground", "#e6e1e5")
    property color subtext0: palette("muted", "#cac4d0")
    property color subtext1: palette("on_surface_variant", "#cac4d0")
    property color surface0: palette("surface_container", "#252229")
    property color surface1: palette("surface_container_high", "#2b2930")
    property color surface2: role("surface_elevated", "#36343a")
    property color overlay0: palette("outline_variant", "#49454f")
    property color overlay1: palette("outline", "#938f99")
    property color overlay2: palette("foreground", "#e6e1e5")
    property color blue: palette("primary", "#d0bcff")
    property color sapphire: palette("secondary", "#ccc2dc")
    property color peach: palette("tertiary", "#efb8c8")
    property color green: role("success", "#a6e3a1")
    property color red: palette("error", "#f2b8b5")
    property color mauve: palette("primary", "#d0bcff")
    property color pink: palette("tertiary", "#efb8c8")
    property color yellow: role("warning", "#f9e2af")
    property color maroon: palette("error", "#f2b8b5")
    property color teal: palette("secondary", "#ccc2dc")

    FileView {
        path: Quickshell.env("HOME") + "/.cache/maho/theme/active.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: reload()

        JsonAdapter {
            id: data
            property int version: 0
            property int palette_version: 0
            property var colors: ({})
            property string mode: "dark"
            property var source: ({})
            property var semantic: ({})
        }
    }
}
