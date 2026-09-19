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
    property color surfaceLow: palette("surface_container_low", mix(surface, foreground, 0.06))
    property color surfaceHigh: palette("surface_container_high", "#2b2930")
    property color surfaceHighest: palette("surface_container_highest", mix(surfaceHigh, foreground, 0.10))
    property color foreground: palette("foreground", "#e6e1e5")
    property color muted: palette("muted", "#cac4d0")
    property color outline: palette("outline", "#938f99")
    property color primary: palette("primary", "#d0bcff")
    property color secondary: palette("secondary", "#ccc2dc")
    property color tertiary: palette("tertiary", "#efb8c8")
    property color error: palette("error", "#f2b8b5")

    readonly property color accent: stableAccent(primary)
    readonly property color textPrimary: alpha(foreground, 0.98)
    readonly property color textBody: alpha(foreground, 0.84)
    readonly property color textSecondary: alpha(foreground, 0.72)
    readonly property color textMuted: alpha(muted, 0.76)
    readonly property color textFaint: alpha(muted, 0.63)

    // Material hierarchy: Hyprland supplies the behind-window diffusion while
    // these translucent layers supply tint, depth and foreground contrast.
    // Keep grayscale text strong; let the blurred wallpaper carry the color.
    readonly property color insetColor: mix(surfaceHigh, background, 0.36)
    readonly property color familyShell: mix(surfaceHigh, background, 0.54)
    readonly property color glassBase: familyShell
    readonly property color centerShell: mix(glassBase, accent, 0.030)

    // Keep the surface translucent enough for the compositor blur to remain
    // visibly part of the material. Optical depth comes from one quiet
    // top-to-bottom wash rather than cross-panel stripes.
    // Slightly denser than the frozen polished checkpoint: background color
    // still leaks through, but application detail is carried by compositor
    // diffusion rather than remaining directly readable through the shell.
    readonly property color popupFill: alpha(mix(familyShell, accent, 0.024), 0.82)
    readonly property color centerFill: alpha(centerShell, 0.82)
    readonly property color shellRim: alpha(foreground, 0.072)
    readonly property color shellTopSpecular: alpha(foreground, 0.045)
    readonly property color shellAccentWash: alpha(accent, 0.024)
    readonly property color shellBottomShade: alpha(background, 0.060)
    readonly property color shellInnerLine: alpha(foreground, 0.056)
    readonly property color outerGlow: alpha(accent, 0.018)

    readonly property color toolbarFill: alpha(mix(surfaceHigh, background, 0.43), 0.44)
    readonly property color toolbarRim: alpha(foreground, 0.050)
    readonly property color sectionFill: alpha(mix(surfaceHigh, background, 0.50), 0.28)

    // Raised delivery control: one quiet interactive plane, not a row of chips.
    readonly property color focusFill: alpha(mix(surfaceHigh, foreground, 0.060), 0.36)
    readonly property color focusHover: alpha(mix(surfaceHigh, foreground, 0.075), 0.43)
    readonly property color focusRim: alpha(foreground, 0.050)
    readonly property color controlTopWash: alpha(foreground, 0.030)
    readonly property color controlBottomShade: alpha(background, 0.050)

    readonly property color controlFill: alpha(mix(surfaceHigh, background, 0.48), 0.32)
    readonly property color controlHover: alpha(mix(surfaceHigh, foreground, 0.065), 0.38)
    readonly property color controlPressed: alpha(mix(surfaceHigh, foreground, 0.090), 0.46)
    readonly property color controlRim: alpha(foreground, 0.048)
    readonly property color controlRimActive: alpha(accent, 0.13)
    readonly property color controlActiveFill: alpha(mix(surfaceHigh, accent, 0.14), 0.50)

    readonly property color badgeFill: alpha(mix(surfaceHigh, accent, 0.06), 0.36)
    readonly property color badgeRim: alpha(foreground, 0.085)
    readonly property color badgeActiveFill: alpha(mix(surfaceHigh, accent, 0.14), 0.46)
    readonly property color badgeActiveRim: alpha(accent, 0.20)

    // Notification cards are intentionally more translucent than the shell.
    // Combined with the already-blurred backing plane this creates nested depth
    // instead of opaque slabs stacked inside an opaque slab.
    readonly property color rowFill: alpha(mix(surfaceHigh, background, 0.18), 0.30)
    readonly property color rowHover: alpha(mix(surfaceHigh, foreground, 0.055), 0.37)
    readonly property color rowUnread: alpha(mix(surfaceHigh, accent, 0.035), 0.32)
    readonly property color rowUnreadHover: alpha(mix(surfaceHigh, accent, 0.055), 0.39)
    readonly property color rowSelected: alpha(mix(surfaceHigh, accent, 0.065), 0.45)
    readonly property color rowRim: alpha(foreground, 0.040)
    readonly property color rowActiveRim: alpha(accent, 0.10)
    readonly property color rowSeparator: alpha(foreground, 0.026)
    readonly property color rowTopWash: alpha(foreground, 0.022)
    readonly property color rowBottomShade: alpha(background, 0.025)
    readonly property color heldTagFill: alpha(mix(surfaceHigh, accent, 0.06), 0.30)
    readonly property color heldTagText: alpha(muted, 0.78)
    readonly property color divider: alpha(foreground, 0.050)

    // Menus sit above moving content, so they are denser than cards while still
    // inheriting some of the same background color and highlight treatment.
    readonly property color menuFill: alpha(mix(surfaceHigh, background, 0.16), 0.94)
    readonly property color menuRim: alpha(foreground, 0.15)
    readonly property color menuHover: alpha(foreground, 0.085)
    readonly property color menuPressed: alpha(foreground, 0.12)

    readonly property color actionFill: alpha(mix(surfaceHigh, accent, 0.075), 0.58)
    readonly property color actionHover: alpha(mix(surfaceHigh, accent, 0.12), 0.68)
    readonly property color actionRim: alpha(accent, 0.16)
    readonly property color criticalRim: alpha(error, 0.36)
    readonly property color criticalWash: alpha(error, 0.052)

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
