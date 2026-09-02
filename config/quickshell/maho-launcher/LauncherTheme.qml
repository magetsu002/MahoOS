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
    readonly property color shellBase: mix(surfaceHigh, background, 0.31)
    readonly property color insetBase: mix(surfaceHigh, background, 0.39)

    readonly property color shellFill: alpha(shellBase, 0.76)
    readonly property color shellRim: alpha(mix(outline, foreground, 0.14), 0.16)
    readonly property color shellTopGlow: alpha(accent, 0.045)
    readonly property color shellInnerLine: alpha(foreground, 0.025)

    readonly property color controlFill: alpha(mix(insetBase, foreground, 0.08), 0.20)
    readonly property color controlHover: alpha(mix(insetBase, accent, 0.20), 0.34)
    readonly property color controlPressed: alpha(mix(insetBase, accent, 0.30), 0.44)
    readonly property color controlRim: alpha(mix(outline, accent, 0.12), 0.16)

    readonly property color searchFill: alpha(insetBase, 0.26)
    readonly property color searchFocusedFill: alpha(mix(insetBase, accent, 0.08), 0.31)
    readonly property color searchRim: alpha(outline, 0.11)
    readonly property color searchFocusRim: alpha(accent, 0.28)

    readonly property color segmentFill: alpha(mix(insetBase, background, 0.12), 0.20)
    readonly property color segmentRim: alpha(outline, 0.09)
    readonly property color selectedSegment: alpha(mix(insetBase, accent, 0.34), 0.58)
    readonly property color selectedSegmentTop: alpha(mix(surfaceHigh, accent, 0.24), 0.62)
    readonly property color selectedSegmentRim: alpha(accent, 0.24)

    readonly property color resultsFill: alpha(mix(insetBase, background, 0.18), 0.12)
    readonly property color resultsRim: alpha(outline, 0.075)
    readonly property color rowHover: alpha(mix(insetBase, accent, 0.10), 0.20)
    readonly property color selectedRow: alpha(mix(insetBase, accent, 0.28), 0.50)
    readonly property color selectedRowTop: alpha(mix(surfaceHigh, accent, 0.20), 0.56)
    readonly property color selectedRowRim: alpha(accent, 0.20)
    readonly property color divider: alpha(mix(outline, foreground, 0.10), 0.075)

    readonly property color focusGlow: alpha(accent, 0.16)
    readonly property color subtleGlow: alpha(accent, 0.035)

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
