import QtQuick 2.15

Item {
    id: root

    property real uiScale: 1
    property real controlWidth: 128
    property string iconName: "power"
    property string label: ""
    property string fontFamily: "Noto Sans"
    signal triggered()

    readonly property bool hovered: pointer.containsMouse
    readonly property bool pressed: pointer.pressed

    width: controlWidth * uiScale
    height: 52 * uiScale
    scale: root.pressed ? 0.96 : (root.hovered ? 1.025 : 1)
    opacity: root.enabled ? 1 : 0.46

    Behavior on scale {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        antialiasing: true
        color: root.pressed
            ? Qt.rgba(0.031, 0.106, 0.227, 0.30)
            : (root.hovered
                ? Qt.rgba(0.031, 0.106, 0.227, 0.26)
                : Qt.rgba(0.031, 0.106, 0.227, 0.20))
        border.width: Math.max(1, root.uiScale)
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

    Row {
        anchors.centerIn: parent
        spacing: 14 * root.uiScale

        Item {
            width: 20 * root.uiScale
            height: 20 * root.uiScale
            anchors.verticalCenter: parent.verticalCenter
            scale: root.pressed ? 0.92 : (root.hovered ? 1.06 : 1)

            Behavior on scale {
                NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
            }

            MahoSddmIcon {
                anchors.centerIn: parent
                width: 19 * root.uiScale
                height: 19 * root.uiScale
                name: root.iconName
                iconOpacity: root.hovered ? 1 : 0.98
            }
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: root.label
            color: Qt.rgba(0.957, 0.976, 1.0, root.hovered ? 1 : 0.98)
            font.pixelSize: 13 * root.uiScale
            font.family: root.fontFamily
            font.weight: Font.DemiBold
            style: Text.Raised
            styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.30)

            Behavior on color { ColorAnimation { duration: 130 } }
        }
    }

    MouseArea {
        id: pointer
        objectName: "mahoSddmActionPointer"
        anchors.fill: parent
        enabled: root.enabled
        hoverEnabled: true
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.triggered()
    }
}
