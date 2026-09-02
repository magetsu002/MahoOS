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

    property color background: palette("background", "#151313")
    property color surface: palette("surface_container", "#211e1e")
    property color surfaceHigh: palette("surface_container_high", "#2b2727")
    property color foreground: palette("foreground", "#eee9e7")
    property color muted: palette("muted", "#c9c0bd")
    property color outline: palette("outline", "#918986")
    property color primary: palette("primary", "#b7a39d")

    readonly property color accent: stableAccent(primary)
    readonly property color textPrimary: foreground
    readonly property color textSecondary: alpha(mix(muted, foreground, 0.06), 0.82)

    // Neutral glass is the authored material. Palette V2 contributes reflected
    // environmental tint; it does not repaint the whole launcher red/blue/green.
    readonly property color glassNeutral: Qt.rgba(0.055, 0.058, 0.066, 1)
    readonly property color glassRaised: Qt.rgba(0.078, 0.080, 0.089, 1)
    readonly property color environmentTint: mix(surfaceHigh, accent, 0.10)
    readonly property color shellBase: mix(glassNeutral, environmentTint, 0.10)
    readonly property color insetBase: mix(glassRaised, environmentTint, 0.08)

    // Let the compositor's real backdrop blur remain visually dominant.
    readonly property color shellFill: alpha(shellBase, 0.58)
    readonly property color shellRim: alpha(mix(outline, foreground, 0.22), 0.20)
    readonly property color shellTopSpecular: alpha(mix(foreground, accent, 0.06), 0.075)
    readonly property color shellAccentWash: alpha(accent, 0.032)
    readonly property color shellBottomShade: alpha(background, 0.15)
    readonly property color shellInnerLine: alpha(foreground, 0.060)
    readonly property color shellSideLine: alpha(foreground, 0.018)
    readonly property color outerGlow: alpha(accent, 0.028)

    readonly property color controlFill: alpha(mix(insetBase, foreground, 0.05), 0.24)
    readonly property color controlHover: alpha(mix(insetBase, accent, 0.22), 0.40)
    readonly property color controlPressed: alpha(mix(insetBase, accent, 0.30), 0.52)
    readonly property color controlRim: alpha(mix(outline, foreground, 0.12), 0.16)
    readonly property color controlRimActive: alpha(accent, 0.28)
    readonly property color controlInnerRim: alpha(foreground, 0.050)
    readonly property color controlGlyph: alpha(foreground, 0.92)

    readonly property color searchFill: alpha(mix(insetBase, glassNeutral, 0.26), 0.28)
    readonly property color searchFocusedFill: alpha(mix(insetBase, accent, 0.08), 0.34)
    readonly property color searchRim: alpha(mix(outline, foreground, 0.08), 0.12)
    readonly property color searchFocusRim: alpha(accent, 0.30)
    readonly property color searchSpecular: alpha(foreground, 0.030)
    readonly property color searchSpecularFocus: alpha(mix(foreground, accent, 0.18), 0.060)
    readonly property color searchGlyph: alpha(foreground, 0.72)

    readonly property color segmentFill: alpha(mix(glassNeutral, insetBase, 0.42), 0.22)
    readonly property color segmentRim: alpha(outline, 0.10)
    readonly property color selectedSegment: alpha(mix(insetBase, accent, 0.34), 0.52)
    readonly property color selectedSegmentTop: alpha(mix(foreground, accent, 0.20), 0.18)
    readonly property color selectedSegmentBottom: alpha(mix(glassNeutral, accent, 0.24), 0.54)
    readonly property color selectedSegmentRim: alpha(accent, 0.28)

    readonly property color resultsFill: alpha(mix(glassNeutral, background, 0.18), 0.16)
    readonly property color resultsRim: alpha(outline, 0.085)
    readonly property color resultsSpecular: alpha(foreground, 0.026)

    readonly property color rowHover: alpha(mix(insetBase, accent, 0.14), 0.28)
    readonly property color rowHoverRim: alpha(mix(outline, accent, 0.08), 0.075)
    readonly property color selectedRow: alpha(mix(insetBase, accent, 0.30), 0.50)
    readonly property color selectedRowTop: alpha(mix(foreground, accent, 0.20), 0.15)
    readonly property color selectedRowBottom: alpha(mix(glassNeutral, accent, 0.28), 0.56)
    readonly property color selectedRowRim: alpha(accent, 0.23)
    readonly property color selectedRowSpecular: alpha(mix(foreground, accent, 0.12), 0.070)
    readonly property color divider: alpha(mix(outline, foreground, 0.14), 0.085)

    readonly property color iconWellFill: alpha(foreground, 0.022)
    readonly property color iconWellHover: alpha(mix(insetBase, foreground, 0.05), 0.12)
    readonly property color iconWellSelected: alpha(mix(insetBase, accent, 0.16), 0.20)
    readonly property color iconWellRim: alpha(outline, 0.050)
    readonly property color iconWellSelectedRim: alpha(accent, 0.12)

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
