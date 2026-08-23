import QtQuick
import QtQuick.Effects

Item {
    id: root

    property alias source: iconSource.source
    property color tint: "white"
    property alias asynchronous: iconSource.asynchronous

    Image {
        id: iconSource
        anchors.fill: parent
        fillMode: Image.PreserveAspectFit
        sourceSize.width: Math.max(1, width)
        sourceSize.height: Math.max(1, height)
        visible: false
    }

    MultiEffect {
        anchors.fill: parent
        source: iconSource
        colorization: 1.0
        colorizationColor: root.tint
    }
}
