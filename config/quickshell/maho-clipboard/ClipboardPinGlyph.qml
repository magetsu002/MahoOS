import QtQuick

Item {
    id: root

    required property color glyphColor

    implicitWidth: 17
    implicitHeight: 17

    // Pinning is an action, not decoration. Keep the glyph readable even when
    // its surrounding row is using a very quiet wallpaper-derived palette.
    readonly property color visibleColor: Qt.rgba(
        glyphColor.r,
        glyphColor.g,
        glyphColor.b,
        Math.max(0.90, glyphColor.a)
    )

    readonly property bool geometryReady:
        cap.width > 0 && leftShoulder.width > 0 && rightShoulder.width > 0
        && shelf.width > 0 && needle.height > 0
    readonly property color renderedColor: cap.color

    Item {
        id: geometry
        anchors.centerIn: parent
        width: Math.min(root.width, root.height)
        height: width

        Rectangle {
            id: cap
            objectName: "pinCap"
            x: geometry.width * 0.29
            y: geometry.height * 0.17
            width: geometry.width * 0.42
            height: Math.max(1.7, geometry.width * 0.10)
            radius: height / 2
            color: root.visibleColor
        }

        Rectangle {
            id: leftShoulder
            objectName: "pinLeftShoulder"
            x: geometry.width * 0.25
            y: geometry.height * 0.28
            width: geometry.width * 0.34
            height: Math.max(1.7, geometry.width * 0.10)
            radius: height / 2
            rotation: 64
            transformOrigin: Item.Left
            color: root.visibleColor
        }

        Rectangle {
            id: rightShoulder
            objectName: "pinRightShoulder"
            x: geometry.width * 0.75
            y: geometry.height * 0.28
            width: geometry.width * 0.34
            height: Math.max(1.7, geometry.width * 0.10)
            radius: height / 2
            rotation: 116
            transformOrigin: Item.Left
            color: root.visibleColor
        }

        Rectangle {
            id: shelf
            objectName: "pinShelf"
            x: geometry.width * 0.20
            y: geometry.height * 0.55
            width: geometry.width * 0.60
            height: Math.max(1.7, geometry.width * 0.10)
            radius: height / 2
            color: root.visibleColor
        }

        Rectangle {
            id: needle
            objectName: "pinNeedle"
            anchors.horizontalCenter: parent.horizontalCenter
            y: geometry.height * 0.57
            width: Math.max(1.7, geometry.width * 0.10)
            height: geometry.height * 0.29
            radius: width / 2
            color: root.visibleColor
        }
    }
}
