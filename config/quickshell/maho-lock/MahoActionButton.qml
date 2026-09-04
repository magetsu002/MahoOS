import QtQuick

Item {
    id: root

    required property var theme
    property string iconName: "power"
    property string label: ""
    property bool enabled: true
    signal triggered()

    readonly property bool hovered: pointer.containsMouse
    readonly property bool pressed: pointer.pressed

    implicitWidth: Math.max(104, labelText.implicitWidth + 54)
    implicitHeight: 42

    scale: root.pressed ? 0.96 : (root.hovered ? 1.025 : 1)
    opacity: root.enabled ? 1 : 0.46

    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        id: iconDisc
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 34
        height: 34
        radius: 17
        color: root.pressed
            ? Qt.rgba(1, 1, 1, 0.16)
            : (root.hovered ? Qt.rgba(1, 1, 1, 0.115) : Qt.rgba(1, 1, 1, 0.070))
        border.width: 1
        border.color: root.hovered
            ? Qt.rgba(1, 1, 1, 0.16)
            : Qt.rgba(1, 1, 1, 0.085)

        scale: root.pressed ? 0.92 : (root.hovered ? 1.06 : 1)

        Behavior on color {
            ColorAnimation { duration: 130; easing.type: Easing.OutCubic }
        }

        Behavior on border.color {
            ColorAnimation { duration: 130; easing.type: Easing.OutCubic }
        }

        Behavior on scale {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }

        MahoIconV2 {
            anchors.centerIn: parent
            width: 18
            height: 18
            name: root.iconName
            iconOpacity: root.hovered ? 0.96 : 0.84

            scale: root.pressed ? 0.90 : 1
            Behavior on scale {
                NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
            }
        }
    }

    Text {
        id: labelText
        x: iconDisc.width + 11 + (root.hovered ? 2 : 0)
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        color: Qt.rgba(1, 1, 1, root.hovered ? 0.98 : 0.88)
        font.pixelSize: 13
        font.weight: Font.Normal

        Behavior on x {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }

        Behavior on color {
            ColorAnimation { duration: 130 }
        }
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        cursorShape: Qt.PointingHandCursor
        onReleased: function(mouse) {
            if (containsMouse && mouse.button === Qt.LeftButton)
                root.triggered()
        }
    }
}
