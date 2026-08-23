import QtQuick

MahoCard {
    id: slider

    property string iconText: ""
    property string titleText: ""
    property int value: 0
    property int maximum: 100
    property color accent: theme ? theme.primary : "#d0bcff"
    property bool sliderEnabled: true

    signal valueRequested(real value)

    height: 56
    interactive: false

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 14
        anchors.verticalCenter: parent.verticalCenter
        text: slider.iconText
        color: slider.accent
        font.family: "JetBrainsMono Nerd Font"
        font.pixelSize: 17

        Behavior on color { ColorAnimation { duration: 360 } }
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: 49
        anchors.top: parent.top
        anchors.topMargin: 9
        text: slider.titleText
        color: slider.theme ? slider.theme.foreground : "white"
        font.pixelSize: 10
        font.weight: Font.DemiBold

        Behavior on color { ColorAnimation { duration: 360 } }
    }

    Text {
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.top: parent.top
        anchors.topMargin: 9
        text: slider.sliderEnabled ? slider.value + "%" : "N/A"
        color: slider.theme ? slider.theme.muted : "#bdb8c3"
        font.pixelSize: 9

        Behavior on color { ColorAnimation { duration: 360 } }
    }

    Rectangle {
        id: track
        anchors.left: parent.left
        anchors.leftMargin: 49
        anchors.right: parent.right
        anchors.rightMargin: 14
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 12
        height: 5
        radius: 3
        color: slider.theme
            ? slider.theme.alpha(slider.theme.muted, 0.16)
            : "#303036"

        Rectangle {
            width: slider.sliderEnabled
                ? parent.width * Math.min(slider.maximum, Math.max(0, slider.value)) / slider.maximum
                : 0
            height: parent.height
            radius: parent.radius
            color: slider.accent

            Behavior on width {
                NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
            }

            Behavior on color { ColorAnimation { duration: 360 } }
        }

        MouseArea {
            anchors.fill: parent
            enabled: slider.sliderEnabled
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor

            function applyAt(x) {
                slider.valueRequested(
                    Math.max(0, Math.min(slider.maximum, x / width * slider.maximum))
                )
            }

            onPressed: function(mouse) { applyAt(mouse.x) }
            onPositionChanged: function(mouse) {
                if (pressed)
                    applyAt(mouse.x)
            }
        }
    }
}
