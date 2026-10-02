import QtQuick

QtObject {
    id: root

    property var palette
    property bool reducedTransparency: false
    property bool reducedMotion: false

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

    readonly property color background: palette ? palette.background : "#120d0d"
    readonly property color surface: palette ? palette.surface : "#211818"
    readonly property color surfaceElevated: palette ? palette.surfaceElevated : "#302424"
    readonly property color foreground: palette ? palette.foreground : "#f4eeee"
    readonly property color muted: palette ? palette.muted : "#b7aaaa"
    readonly property color accent: palette ? palette.accent : "#d8aaaa"
    readonly property bool lightMode: palette ? palette.mode === "light" : false

    readonly property color textPrimary: alpha(foreground, 0.98)
    readonly property color textBody: alpha(foreground, 0.84)
    readonly property color textSecondary: alpha(foreground, 0.70)
    readonly property color textFaint: alpha(muted, 0.62)

    readonly property color shellFill: reducedTransparency
        ? mix(surface, background, 0.16)
        : alpha(mix(surface, background, 0.18), lightMode ? 0.72 : 0.62)
    readonly property color sidebarFill: reducedTransparency
        ? mix(background, surface, 0.30)
        : alpha(mix(background, surface, 0.28), lightMode ? 0.82 : 0.72)
    readonly property color contentFill: reducedTransparency
        ? surface
        : alpha(mix(surface, accent, 0.035), lightMode ? 0.64 : 0.52)

    readonly property color shellRim: alpha(foreground, lightMode ? 0.20 : 0.13)
    readonly property color shellInnerRim: alpha(foreground, lightMode ? 0.08 : 0.045)
    readonly property color divider: alpha(foreground, lightMode ? 0.11 : 0.065)

    readonly property color searchFill: reducedTransparency
        ? mix(surfaceElevated, background, 0.34)
        : alpha(mix(surfaceElevated, background, 0.32), 0.38)
    readonly property color searchHover: alpha(foreground, 0.055)
    readonly property color searchFocusRim: alpha(accent, 0.26)

    readonly property color navHover: alpha(foreground, 0.055)
    readonly property color navPressed: alpha(foreground, lightMode ? 0.11 : 0.085)
    readonly property color navSelected: alpha(mix(surfaceElevated, accent, 0.16), lightMode ? 0.62 : 0.50)
    readonly property color navSelectedHover: alpha(mix(surfaceElevated, accent, 0.20), lightMode ? 0.70 : 0.58)
    readonly property color navSelectedRim: alpha(foreground, 0.045)

    readonly property color rowFill: reducedTransparency
        ? surfaceElevated
        : alpha(mix(surfaceElevated, surface, 0.24), lightMode ? 0.66 : 0.42)
    readonly property color rowHover: alpha(mix(surfaceElevated, foreground, 0.055), lightMode ? 0.72 : 0.50)
    readonly property color rowRim: alpha(foreground, lightMode ? 0.11 : 0.060)
    readonly property color rowInnerRim: alpha(foreground, 0.028)

    readonly property color controlFill: alpha(mix(surfaceElevated, background, 0.30), reducedTransparency ? 1.0 : 0.44)
    readonly property color controlHover: alpha(mix(surfaceElevated, foreground, 0.05), reducedTransparency ? 1.0 : 0.60)
    readonly property color controlPressed: alpha(mix(surfaceElevated, foreground, 0.08), reducedTransparency ? 1.0 : 0.68)
    readonly property color controlActive: alpha(mix(surfaceElevated, accent, 0.18), reducedTransparency ? 1.0 : 0.72)
    readonly property color controlRim: alpha(foreground, 0.075)
    readonly property color controlActiveRim: alpha(accent, 0.20)
}
