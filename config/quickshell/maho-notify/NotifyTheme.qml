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

    function mix(first, second, amount) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            first.r * (1 - t) + second.r * t,
            first.g * (1 - t) + second.g * t,
            first.b * (1 - t) + second.b * t,
            first.a * (1 - t) + second.a * t
        )
    }

    function stableAccent(source) {
        const saturation = source.hsvSaturation
        if (saturation < 0.08)
            return mix(foreground, surfaceHigh, 0.38)

        const hue = source.hsvHue < 0 ? 0 : source.hsvHue
        return Qt.hsva(
            hue,
            Math.max(0.20, Math.min(0.62, saturation)),
            Math.max(0.62, Math.min(0.88, source.hsvValue)),
            1
        )
    }

    property color background: palette("background", "#151318")
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

    readonly property color accent: stableAccent(primary)
    readonly property color textPrimary: foreground
    readonly property color textSecondary: alpha(muted, 0.78)

    // Shared Maho material grammar. Notify deliberately stays compositor-safe:
    // popup/center PanelWindows remain transparent and only the authored cards
    // carry translucency, avoiding a full-screen blur rule for tiny surfaces.
    readonly property color insetColor: mix(surfaceHigh, background, 0.36)
    readonly property color familyShell: mix(surfaceHigh, background, 0.54)

    readonly property color popupFill: alpha(familyShell, 0.78)
    readonly property color centerFill: alpha(familyShell, 0.74)
    readonly property color shellRim: alpha(foreground, 0.095)
    readonly property color shellTopSpecular: alpha(foreground, 0.034)
    readonly property color shellAccentWash: alpha(accent, 0.020)
    readonly property color shellBottomShade: alpha(accent, 0.034)
    readonly property color shellInnerLine: alpha(foreground, 0.055)
    readonly property color outerGlow: alpha(accent, 0.018)

    readonly property color controlFill: alpha(mix(surfaceHigh, background, 0.60), 0.42)
    readonly property color controlHover: alpha(mix(surfaceHigh, accent, 0.08), 0.50)
    readonly property color controlPressed: alpha(mix(surfaceHigh, accent, 0.12), 0.56)
    readonly property color controlRim: alpha(foreground, 0.055)
    readonly property color controlRimActive: alpha(accent, 0.14)

    readonly property color badgeFill: alpha(mix(surfaceHigh, accent, 0.10), 0.48)
    readonly property color badgeRim: alpha(accent, 0.13)

    readonly property color rowFill: alpha(mix(surfaceHigh, background, 0.64), 0.30)
    readonly property color rowHover: alpha(mix(surfaceHigh, background, 0.58), 0.43)
    readonly property color rowUnread: alpha(mix(surfaceHigh, accent, 0.075), 0.45)
    readonly property color rowUnreadHover: alpha(mix(surfaceHigh, accent, 0.10), 0.52)
    readonly property color rowSelected: alpha(mix(surfaceHigh, accent, 0.10), 0.54)
    readonly property color rowRim: alpha(foreground, 0.045)
    readonly property color rowActiveRim: alpha(accent, 0.11)
    readonly property color divider: alpha(foreground, 0.040)

    readonly property color actionFill: alpha(mix(surfaceHigh, accent, 0.08), 0.46)
    readonly property color actionHover: alpha(mix(surfaceHigh, accent, 0.13), 0.56)
    readonly property color actionRim: alpha(accent, 0.13)
    readonly property color criticalRim: alpha(error, 0.34)
    readonly property color criticalWash: alpha(error, 0.055)

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
