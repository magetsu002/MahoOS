import QtQuick
import QtQuick.Effects

Rectangle {
    id: root

    required property var theme
    property bool focused: false
    property bool strong: false
    property bool hovered: false
    property bool pressed: false
    property real errorAmount: 0

    readonly property real fillAlpha: root.strong
        ? (root.pressed ? 0.28 : (root.hovered ? 0.25 : 0.22))
        : (root.focused ? 0.27 : 0.21)

    readonly property color neutral: Qt.rgba(0.804, 0.910, 1.000, 1)
    readonly property color calmTint: root.theme.mix(
        root.neutral,
        root.theme.accent,
        root.focused ? 0.08 : 0.05
    )
    readonly property color errorTint: root.theme.mix(
        root.calmTint,
        root.theme.error,
        Math.max(0, Math.min(1, root.errorAmount)) * 0.16
    )

    radius: height / 2
    color: root.theme.alpha(root.errorTint, root.fillAlpha)
    border.width: Math.max(1, height / 60)
    border.color: root.errorAmount > 0.01
        ? root.theme.alpha(root.theme.error, 0.42 * root.errorAmount)
        : (root.focused
            ? Qt.rgba(0.882, 0.953, 1.000, 0.55)
            : Qt.rgba(0.882, 0.953, 1.000, root.strong ? 0.40 : 0.46))

    layer.enabled: true
    layer.effect: MultiEffect {
        shadowEnabled: true
        shadowOpacity: root.strong ? 0.15 : 0.19
        shadowBlur: 0.82
        shadowHorizontalOffset: 0
        shadowVerticalOffset: 5
        shadowColor: Qt.rgba(0.020, 0.102, 0.235, 0.72)
        blurMax: 24
    }

    scale: root.pressed ? 0.975 : (root.hovered ? 1.012 : (root.focused ? 1.006 : 1))

    Behavior on color {
        ColorAnimation { duration: 140; easing.type: Easing.OutCubic }
    }

    Behavior on border.color {
        ColorAnimation { duration: 140; easing.type: Easing.OutCubic }
    }

    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    // A single low-contrast inner edge. No painted "gloss" gradient.
    Rectangle {
        anchors.fill: parent
        anchors.margins: Math.max(1, root.height / 60)
        radius: Math.max(0, root.radius - 1)
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, root.focused ? 0.15 : 0.10)
    }

    // Very faint top response to keep the surface from reading as flat plastic.
    Rectangle {
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.topMargin: 1
        width: Math.max(0, parent.width - parent.height * 1.05)
        height: 1
        radius: 1
        color: Qt.rgba(1, 1, 1, root.focused ? 0.18 : 0.13)
    }
}
