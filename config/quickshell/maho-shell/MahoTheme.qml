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

    function semanticPalette(name, fallback) {
        const roles = data.semantic
        if (roles && roles[name] !== undefined && roles[name] !== null)
            return roles[name]
        return fallback
    }

    function alpha(c, a) {
        return Qt.rgba(c.r, c.g, c.b, a)
    }

    function mix(first, second, amount) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            first.r * (1 - t) + second.r * t,
            first.g * (1 - t) + second.g * t,
            first.b * (1 - t) + second.b * t,
            first.a * (1 - t) + second.a * t
        )
    }

    property color background: palette("background", "#141218")
    property color surface: palette("surface_container", "#211f26")
    property color surfaceHigh: palette("surface_container_high", "#2b2930")
    property color foreground: palette("foreground", "#e6e1e5")
    property color muted: palette("muted", "#cac4d0")
    property color outline: palette("outline", "#938f99")
    property color primary: palette("primary", "#d0bcff")
    property color secondary: palette("secondary", "#ccc2dc")
    property color tertiary: palette("tertiary", "#efb8c8")
    property color error: palette("error", "#f2b8b5")

    // Palette V2 is additive inside the stable version-1 envelope. Existing
    // Maho Edge consumers continue to use the legacy color properties above;
    // newer surfaces can consume semantic roles without changing Edge visuals.
    readonly property int paletteVersion: Number(data.palette_version || 1)
    readonly property string paletteMode: String(data.palette_mode || "")
    readonly property color semanticBackground: semanticPalette("background", background)
    readonly property color semanticSurface: semanticPalette("surface", surface)
    readonly property color semanticSurfaceElevated: semanticPalette("surface_elevated", surfaceHigh)
    readonly property color semanticForeground: semanticPalette("foreground", foreground)
    readonly property color semanticForegroundMuted: semanticPalette("foreground_muted", muted)
    readonly property color semanticAccent: semanticPalette("accent", primary)
    readonly property color semanticAccentSoft: semanticPalette("accent_soft", mix(primary, surface, 0.18))
    readonly property color semanticBorder: semanticPalette("border", outline)
    readonly property color semanticFocus: semanticPalette("focus", primary)
    readonly property color semanticShadow: semanticPalette("shadow", "#000000")

    // MahoTheme is already instantiated exactly once by the persistent ShellRoot.
    // This narrow bootstrap keeps the accepted Edge tree byte-for-byte intact
    // while making Maho Dock a sibling shell surface in the same Quickshell
    // process. It is not a second daemon or a separately launched shell.
    MahoDockRuntime {
        theme: theme
    }

    FileView {
        path: Quickshell.env("HOME") + "/.cache/maho/theme/active.json"
        watchChanges: true
        blockLoading: true
        onFileChanged: reload()

        JsonAdapter {
            id: data
            property int version: 0
            property int palette_version: 0
            property string palette_mode: ""
            property var colors: ({})
            property var semantic: ({})
            property string mode: "dark"
            property var source: ({})
            property var analysis: ({})
        }
    }
}
