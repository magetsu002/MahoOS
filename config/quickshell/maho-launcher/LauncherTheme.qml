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
    readonly property color textSecondary: alpha(muted, 0.78)

    // Deliberately use the same material grammar as Maho Link / Bluetooth:
    // semantic palette surfaces stay dark and calm while compositor blur carries
    // the live desktop light through the translucent overlay around the panel.
    readonly property color insetColor: mix(surfaceHigh, background, 0.36)
    readonly property color familyShell: mix(surfaceHigh, background, 0.28)

    readonly property color shellFill: alpha(familyShell, 0.965)
    readonly property color shellRim: alpha(outline, 0.065)
    readonly property color shellTopSpecular: "transparent"
    readonly property color shellAccentWash: "transparent"
    readonly property color shellBottomShade: "transparent"
    readonly property color shellInnerLine: alpha(foreground, 0.020)
    readonly property color shellSideLine: "transparent"
    readonly property color outerGlow: alpha(accent, 0.006)

    readonly property color controlFill: alpha(insetColor, 0.82)
    readonly property color controlHover: alpha(mix(insetColor, accent, 0.07), 0.90)
    readonly property color controlPressed: alpha(mix(insetColor, accent, 0.12), 0.94)
    readonly property color controlRim: alpha(outline, 0.070)
    readonly property color controlRimActive: alpha(accent, 0.15)
    readonly property color controlInnerRim: alpha(foreground, 0.020)
    readonly property color controlGlyph: alpha(foreground, 0.90)

    readonly property color searchFill: alpha(mix(insetColor, background, 0.06), 0.88)
    readonly property color searchFocusedFill: alpha(mix(insetColor, accent, 0.055), 0.92)
    readonly property color searchRim: alpha(outline, 0.070)
    readonly property color searchFocusRim: alpha(accent, 0.15)
    readonly property color searchSpecular: alpha(foreground, 0.016)
    readonly property color searchSpecularFocus: alpha(mix(foreground, accent, 0.10), 0.030)
    readonly property color searchGlyph: alpha(foreground, 0.72)

    readonly property color segmentFill: alpha(mix(insetColor, background, 0.08), 0.84)
    readonly property color segmentRim: alpha(outline, 0.065)
    readonly property color selectedSegment: alpha(mix(insetColor, accent, 0.11), 0.96)
    readonly property color selectedSegmentTop: alpha(mix(foreground, accent, 0.10), 0.055)
    readonly property color selectedSegmentBottom: alpha(mix(insetColor, accent, 0.11), 0.96)
    readonly property color selectedSegmentRim: alpha(accent, 0.12)

    readonly property color resultsFill: alpha(mix(insetColor, background, 0.10), 0.92)
    readonly property color resultsRim: alpha(outline, 0.070)
    readonly property color resultsSpecular: alpha(foreground, 0.014)

    readonly property color rowHover: alpha(accent, 0.050)
    readonly property color rowHoverRim: alpha(accent, 0.070)
    readonly property color selectedRow: alpha(mix(insetColor, accent, 0.11), 0.97)
    readonly property color selectedRowTop: alpha(mix(foreground, accent, 0.08), 0.035)
    readonly property color selectedRowBottom: alpha(mix(insetColor, accent, 0.11), 0.97)
    readonly property color selectedRowRim: alpha(accent, 0.12)
    readonly property color selectedRowSpecular: alpha(foreground, 0.022)
    readonly property color divider: alpha(outline, 0.032)

    // Real application artwork should sit directly on the material, not inside
    // generic white icon tiles. Wells only appear as a whisper on interaction.
    readonly property color iconWellFill: "transparent"
    readonly property color iconWellHover: alpha(foreground, 0.025)
    readonly property color iconWellSelected: alpha(accent, 0.050)
    readonly property color iconWellRim: "transparent"
    readonly property color iconWellSelectedRim: alpha(accent, 0.060)

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
