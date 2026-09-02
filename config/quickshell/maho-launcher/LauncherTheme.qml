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
    readonly property color textSecondary: alpha(mix(muted, foreground, 0.06), 0.80)

    // The compositor owns the blur. QML contributes a very light neutral film
    // and just enough Palette V2 tint to make the glass feel environmentally lit.
    readonly property color glassNeutral: Qt.rgba(0.040, 0.043, 0.050, 1)
    readonly property color glassRaised: Qt.rgba(0.067, 0.070, 0.079, 1)
    readonly property color environmentTint: mix(surfaceHigh, accent, 0.07)
    readonly property color shellBase: mix(glassNeutral, environmentTint, 0.065)
    readonly property color insetBase: mix(glassRaised, environmentTint, 0.055)

    readonly property color shellFill: alpha(shellBase, 0.48)
    readonly property color shellRim: alpha(mix(outline, foreground, 0.18), 0.15)

    // The shell's large child gradient is rectangular in QtQuick even when its
    // parent Rectangle has a radius. Keep that child optically inert so the
    // rounded shell itself is the only material reaching the four corners.
    // The rounded rim + inset lines retain the glass depth without square halos.
    readonly property color shellTopSpecular: alpha(mix(foreground, accent, 0.04), 0.0)
    readonly property color shellAccentWash: alpha(accent, 0.0)
    readonly property color shellBottomShade: alpha(background, 0.0)
    readonly property color shellInnerLine: alpha(foreground, 0.042)
    readonly property color shellSideLine: alpha(foreground, 0.012)
    readonly property color outerGlow: alpha(accent, 0.018)

    readonly property color controlFill: alpha(mix(insetBase, foreground, 0.05), 0.18)
    readonly property color controlHover: alpha(mix(insetBase, accent, 0.20), 0.31)
    readonly property color controlPressed: alpha(mix(insetBase, accent, 0.28), 0.42)
    readonly property color controlRim: alpha(mix(outline, foreground, 0.12), 0.13)
    readonly property color controlRimActive: alpha(accent, 0.22)
    readonly property color controlInnerRim: alpha(foreground, 0.038)
    readonly property color controlGlyph: alpha(foreground, 0.92)

    readonly property color searchFill: alpha(mix(insetBase, glassNeutral, 0.26), 0.20)
    readonly property color searchFocusedFill: alpha(mix(insetBase, accent, 0.07), 0.25)
    readonly property color searchRim: alpha(mix(outline, foreground, 0.08), 0.085)
    readonly property color searchFocusRim: alpha(accent, 0.22)
    readonly property color searchSpecular: alpha(foreground, 0.024)
    readonly property color searchSpecularFocus: alpha(mix(foreground, accent, 0.15), 0.048)
    readonly property color searchGlyph: alpha(foreground, 0.72)

    readonly property color segmentFill: alpha(mix(glassNeutral, insetBase, 0.42), 0.15)
    readonly property color segmentRim: alpha(outline, 0.070)
    readonly property color selectedSegment: alpha(mix(insetBase, accent, 0.30), 0.40)
    readonly property color selectedSegmentTop: alpha(mix(foreground, accent, 0.18), 0.13)
    readonly property color selectedSegmentBottom: alpha(mix(glassNeutral, accent, 0.22), 0.43)
    readonly property color selectedSegmentRim: alpha(accent, 0.20)

    readonly property color resultsFill: alpha(mix(glassNeutral, background, 0.15), 0.075)
    readonly property color resultsRim: alpha(outline, 0.060)
    readonly property color resultsSpecular: alpha(foreground, 0.018)

    readonly property color rowHover: alpha(mix(insetBase, accent, 0.10), 0.19)
    readonly property color rowHoverRim: alpha(mix(outline, accent, 0.06), 0.048)
    readonly property color selectedRow: alpha(mix(insetBase, accent, 0.26), 0.39)
    readonly property color selectedRowTop: alpha(mix(foreground, accent, 0.16), 0.105)
    readonly property color selectedRowBottom: alpha(mix(glassNeutral, accent, 0.24), 0.43)
    readonly property color selectedRowRim: alpha(accent, 0.17)
    readonly property color selectedRowSpecular: alpha(mix(foreground, accent, 0.10), 0.046)
    readonly property color divider: alpha(mix(outline, foreground, 0.10), 0.034)

    readonly property color iconWellFill: alpha(foreground, 0.015)
    readonly property color iconWellHover: alpha(mix(insetBase, foreground, 0.04), 0.080)
    readonly property color iconWellSelected: alpha(mix(insetBase, accent, 0.13), 0.14)
    readonly property color iconWellRim: alpha(outline, 0.035)
    readonly property color iconWellSelectedRim: alpha(accent, 0.085)

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
