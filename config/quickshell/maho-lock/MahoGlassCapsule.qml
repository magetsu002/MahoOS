import QtQuick

Rectangle {
    id: root

    required property var theme
    property bool focused: false
    property bool strong: false
    property bool hovered: false

    radius: height / 2
    color: "transparent"
    border.width: 1
    border.color: focused
        ? Qt.rgba(1, 1, 1, 0.30)
        : (strong ? Qt.rgba(1, 1, 1, 0.20) : Qt.rgba(1, 1, 1, 0.18))

    Behavior on border.color {
        ColorAnimation { duration: 120 }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.max(0, root.radius - 1)

        gradient: Gradient {
            orientation: Gradient.Vertical

            GradientStop {
                position: 0.00
                color: root.focused
                    ? Qt.rgba(1, 1, 1, 0.175)
                    : (root.strong
                        ? Qt.rgba(1, 1, 1, root.hovered ? 0.155 : 0.135)
                        : Qt.rgba(1, 1, 1, 0.105))
            }

            GradientStop {
                position: 0.42
                color: root.theme.alpha(
                    root.theme.mix(root.theme.surfaceHigh, root.theme.accent, root.focused ? 0.08 : 0.035),
                    root.strong ? 0.46 : 0.34
                )
            }

            GradientStop {
                position: 1.00
                color: Qt.rgba(0.025, 0.032, 0.045, root.strong ? 0.34 : 0.27)
            }
        }
    }

    // Neutral reflected cap: a single material highlight, not a fake glow.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: root.height * 0.42
        anchors.rightMargin: root.height * 0.42
        anchors.topMargin: 1
        height: 1
        radius: 1
        color: Qt.rgba(1, 1, 1, root.focused ? 0.22 : (root.strong ? 0.15 : 0.13))
    }

    // A very restrained lower edge gives the translucent shell thickness.
    Rectangle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: root.height * 0.48
        anchors.rightMargin: root.height * 0.48
        anchors.bottomMargin: 1
        height: 1
        radius: 1
        color: Qt.rgba(0, 0, 0, root.strong ? 0.20 : 0.15)
    }
}
