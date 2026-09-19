import QtQuick
import QtQuick.Shapes

Item {
    id: root
    objectName: "clipboardPinGlyph"

    required property color glyphColor
    property bool filled: false

    implicitWidth: 18
    implicitHeight: 18

    // Preserve a quiet Maho treatment while guaranteeing that the action is
    // visually legible on the dark glass surface.
    readonly property color visibleColor: Qt.rgba(
        glyphColor.r,
        glyphColor.g,
        glyphColor.b,
        Math.max(0.92, glyphColor.a)
    )
    readonly property color renderedColor: visibleColor
    readonly property bool geometryReady:
        vector.width > 0 && vector.height > 0 && vector.scale > 0

    Shape {
        id: vector
        objectName: "clipboardPinVector"
        anchors.centerIn: parent
        width: 18
        height: 18
        scale: Math.min(root.width, root.height) / 18
        antialiasing: true

        // A single proportional vector replaces the old rotated rectangles.
        // The fixed 18x18 view box keeps the pin from stretching at fractional
        // Wayland scales while Shape supplies antialiased joins and caps.
        ShapePath {
            strokeColor: root.visibleColor
            strokeWidth: 1.55
            fillColor: root.filled
                ? root.visibleColor
                : Qt.rgba(
                    root.visibleColor.r,
                    root.visibleColor.g,
                    root.visibleColor.b,
                    0.06
                )
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: "M 5.4 2.8 L 12.6 2.8 L 11.45 7.0 L 14.15 9.55 L 14.15 11.15 L 3.85 11.15 L 3.85 9.55 L 6.55 7.0 Z"
            }
        }

        ShapePath {
            strokeColor: root.visibleColor
            strokeWidth: 1.55
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathMove { x: 9; y: 11.15 }
            PathLine { x: 9; y: 15.65 }
        }
    }
}
