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

        // Neutral app tile: enough structure to read as an application mark,
        // but intentionally not branded as any specific program.
        ShapePath {
            strokeColor: Qt.rgba(
                root.glyphColor.r,
                root.glyphColor.g,
                root.glyphColor.b,
                0.72
            )
            strokeWidth: 1.45
            fillColor: Qt.rgba(
                root.glyphColor.r,
                root.glyphColor.g,
                root.glyphColor.b,
                0.055
            )
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: "M 5.8 4.25 L 18.2 4.25 Q 19.75 4.25 19.75 5.8 L 19.75 18.2 Q 19.75 19.75 18.2 19.75 L 5.8 19.75 Q 4.25 19.75 4.25 18.2 L 4.25 5.8 Q 4.25 4.25 5.8 4.25 Z"
            }
        }

        // Four compact rounded cells give missing-artwork apps a deliberate,
        // premium identity instead of looking like a broken window icon.
        ShapePath {
            strokeColor: "transparent"
            fillColor: Qt.rgba(
                root.glyphColor.r,
                root.glyphColor.g,
                root.glyphColor.b,
                0.68
            )

            PathSvg {
                path: "M 7.35 7 L 9.7 7 Q 10.5 7 10.5 7.8 L 10.5 10.15 Q 10.5 10.95 9.7 10.95 L 7.35 10.95 Q 6.55 10.95 6.55 10.15 L 6.55 7.8 Q 6.55 7 7.35 7 Z M 14.3 13.05 L 16.65 13.05 Q 17.45 13.05 17.45 13.85 L 17.45 16.2 Q 17.45 17 16.65 17 L 14.3 17 Q 13.5 17 13.5 16.2 L 13.5 13.85 Q 13.5 13.05 14.3 13.05 Z"
            }
        }

        ShapePath {
            strokeColor: Qt.rgba(
                root.glyphColor.r,
                root.glyphColor.g,
                root.glyphColor.b,
                0.42
            )
            strokeWidth: 1.05
            fillColor: Qt.rgba(
                root.glyphColor.r,
                root.glyphColor.g,
                root.glyphColor.b,
                0.13
            )
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: "M 14.3 7 L 16.65 7 Q 17.45 7 17.45 7.8 L 17.45 10.15 Q 17.45 10.95 16.65 10.95 L 14.3 10.95 Q 13.5 10.95 13.5 10.15 L 13.5 7.8 Q 13.5 7 14.3 7 Z M 7.35 13.05 L 9.7 13.05 Q 10.5 13.05 10.5 13.85 L 10.5 16.2 Q 10.5 17 9.7 17 L 7.35 17 Q 6.55 17 6.55 16.2 L 6.55 13.85 Q 6.55 13.05 7.35 13.05 Z"
            }
        }
    }
}
