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

    function alpha(color, amount) {
        return Qt.rgba(color.r, color.g, color.b, amount)
    }

    function blend(first, second, amount) {
        return Qt.rgba(
            first.r + (second.r - first.r) * amount,
            first.g + (second.g - first.g) * amount,
            first.b + (second.b - first.b) * amount,
            first.a + (second.a - first.a) * amount
        )
    }

    property color background: palette("background", "#141218")
    property color surface: palette("surface_container", "#211f26")
    property color surfaceHigh: palette("surface_container_high", "#2b2930")
    property color foreground: palette("foreground", "#e6e1e5")
    property color muted: palette("muted", "#cac4d0")
    property color outline: palette("outline", "#938f99")
    property color outlineVariant: palette("outline_variant", "#49454f")
    property color primary: palette("primary", "#d0bcff")
    property color secondary: palette("secondary", "#ccc2dc")

    property color panelTint: alpha(blend(background, surface, 0.64), 0.99)
    property color panelBorder: alpha(blend(outlineVariant, primary, 0.08), 0.58)
    property color searchTint: alpha(blend(surface, surfaceHigh, 0.42), 0.965)
    property color searchBorder: alpha(blend(outlineVariant, primary, 0.12), 0.72)
    property color selectedMode: alpha(primary, 0.18)
    property color selectedResult: alpha(primary, 0.095)
    property color selectedOutline: alpha(primary, 0.52)
    property color focusRing: alpha(primary, 0.74)
    property color keyChip: alpha(surfaceHigh, 0.74)
    property color keyBorder: alpha(blend(outlineVariant, primary, 0.12), 0.82)
    property color divider: alpha(outlineVariant, 0.72)
    property color shadow: alpha(background, 0.68)
    property color mascotGlow: alpha(primary, 0.36)

    FileView {
        path: (Quickshell.env("XDG_CACHE_HOME") || Quickshell.env("HOME") + "/.cache")
            + "/maho/theme/active.json"
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
