import QtQuick
import QtQuick.Shapes

Item {
    id: root
    objectName: "mahoFallbackAppGlyph"

    required property color glyphColor

    implicitWidth: 24
    implicitHeight: 24

    readonly property bool geometryReady:
        vector.width > 0 && vector.height > 0 && vector.scale > 0

    Shape {
        id: vector
        anchors.centerIn: parent
        width: 24
        height: 24
        scale: Math.min(root.width, root.height) / 24
        antialiasing: true

        ShapePath {
            strokeColor: root.glyphColor
            strokeWidth: 1.7
            fillColor: Qt.rgba(
                root.glyphColor.r,
                root.glyphColor.g,
                root.glyphColor.b,
                0.07
            )
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: "M 5.25 4.25 L 18.75 4.25 Q 20.25 4.25 20.25 5.75 L 20.25 18.25 Q 20.25 19.75 18.75 19.75 L 5.25 19.75 Q 3.75 19.75 3.75 18.25 L 3.75 5.75 Q 3.75 4.25 5.25 4.25 Z"
            }
        }

        ShapePath {
            strokeColor: root.glyphColor
            strokeWidth: 1.7
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathMove { x: 4.3; y: 8.25 }
            PathLine { x: 19.7; y: 8.25 }
        }

        ShapePath {
            strokeColor: root.glyphColor
            strokeWidth: 1.55
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathMove { x: 7; y: 6.2 }
            PathLine { x: 7.05; y: 6.2 }
            PathMove { x: 9.5; y: 6.2 }
            PathLine { x: 9.55; y: 6.2 }
        }
    }
}
