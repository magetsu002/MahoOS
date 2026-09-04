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

    function mix(a, b, amount) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            a.r * (1 - t) + b.r * t,
            a.g * (1 - t) + b.g * t,
            a.b * (1 - t) + b.b * t,
            a.a * (1 - t) + b.a * t
        )
    }

    property color background: palette("background", "#121417")
    property color surface: palette("surface_container", "#1d2024")
    property color surfaceHigh: palette("surface_container_high", "#292d31")
    property color foreground: palette("foreground", "#f1f2f4")
    property color muted: palette("muted", "#c7cbd0")
    property color outline: palette("outline", "#8f969e")
    property color primary: palette("primary", "#aeb9ca")
    property color secondary: palette("secondary", "#b9c0ca")
    property color error: palette("error", "#f2b8b5")

    readonly property color accent: {
        const saturation = primary.hsvSaturation
        if (saturation < 0.08)
            return mix(foreground, surfaceHigh, 0.42)
        const hue = primary.hsvHue < 0 ? 0 : primary.hsvHue
        return Qt.hsva(
            hue,
            Math.max(0.18, Math.min(0.54, saturation)),
            Math.max(0.62, Math.min(0.86, primary.hsvValue)),
            1
        )
    }

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
