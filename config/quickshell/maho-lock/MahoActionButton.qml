import QtQuick

Item {
    id: root

    required property var theme
    property string iconName: "power"
    property string label: ""
    property string fontFamily: "Noto Sans"
    property int fontWeight: Font.Normal
    property real fontAxisWeight: 400
    property bool enabled: true
    signal triggered()

    readonly property bool hovered: pointer.containsMouse
    readonly property bool pressed: pointer.pressed

    implicitWidth: Math.max(128, labelText.implicitWidth + 66)
    implicitHeight: 52

    scale: root.pressed ? 0.96 : (root.hovered ? 1.025 : 1)
    opacity: root.enabled ? 1 : 0.46

    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: root.pressed
            ? Qt.rgba(0.031, 0.106, 0.227, 0.30)
            : (root.hovered
                ? Qt.rgba(0.031, 0.106, 0.227, 0.26)
                : Qt.rgba(0.031, 0.106, 0.227, 0.20))
        border.width: 1
        border.color: root.hovered
            ? Qt.rgba(0.90, 0.97, 1.0, 0.30)
            : Qt.rgba(0.90, 0.97, 1.0, 0.18)

        Behavior on color {
            ColorAnimation { duration: 130; easing.type: Easing.OutCubic }
        }

        Behavior on border.color {
            ColorAnimation { duration: 130; easing.type: Easing.OutCubic }
        }
    }

    // Center the visible icon and label as one geometric unit. The previous
    // layout anchored a 38 px invisible icon box to the pill's left edge,
    // which made short labels (especially Sleep) look noticeably off-center.
    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: 14

        Item {
            id: iconDisc
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            height: 20

            scale: root.pressed ? 0.92 : (root.hovered ? 1.06 : 1)

            Behavior on scale {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }

            MahoIconV2 {
                anchors.centerIn: parent
                width: 19
                height: 19
                name: root.iconName
                iconOpacity: root.hovered ? 1.0 : 0.98

                scale: root.pressed ? 0.90 : 1
                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }
            }
        }

        Text {
            id: labelText
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: Qt.rgba(0.957, 0.976, 1.0, root.hovered ? 1.0 : 0.98)
            font.pixelSize: 13
            font.family: root.fontFamily
            font.weight: root.fontWeight
            font.variableAxes: ({ "wght": root.fontAxisWeight })
            style: Text.Raised
            styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.30)

            Behavior on color {
                ColorAnimation { duration: 130 }
            }
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
