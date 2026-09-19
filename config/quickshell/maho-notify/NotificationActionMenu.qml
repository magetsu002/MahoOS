import QtQuick

Rectangle {
    id: menu

    required property var theme
    property bool opened: false
    property string currentMode: ""

    signal actionTriggered(string action)

    width: 206
    implicitHeight: menuColumn.implicitHeight + 12
    radius: 12
    antialiasing: true
    color: theme.menuFill
    border.width: 1
    border.color: theme.menuRim
    visible: opened || opacity > 0.01
    opacity: opened ? 1 : 0
    scale: opened ? 1 : 0.975
    transformOrigin: Item.TopRight

    Behavior on opacity {
        NumberAnimation { duration: menu.opened ? 145 : 105; easing.type: Easing.OutCubic }
    }
    Behavior on scale {
        NumberAnimation { duration: menu.opened ? 155 : 105; easing.type: Easing.OutCubic }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 11
        color: "transparent"
        border.width: 1
        border.color: theme.alpha(theme.foreground, 0.025)
    }

    Column {
        id: menuColumn
        x: 6
        y: 6
        width: parent.width - 12
        spacing: 1

        Repeater {
            model: [
                {"key": "show-now", "icon": "󰐊", "label": "Show now"},
                {"key": "hold-until-free", "icon": "󰔟", "label": "Hold until I'm free"},
                {"key": "always-show", "icon": "󰓎", "label": "Always show like this"},
                {"key": "hold-gaming", "icon": "󰊴", "label": "Hold during gaming"},
                {"key": "history-only", "icon": "󰋚", "label": "History only"}
            ]

            Item {
                required property var modelData
                width: menuColumn.width
                height: 38

                Rectangle {
                    anchors.fill: parent
                    radius: 9
                    color: actionMouse.pressed
                        ? theme.menuPressed
                        : (actionMouse.containsMouse ? theme.menuHover : "transparent")

                    Behavior on color {
                        ColorAnimation { duration: 110; easing.type: Easing.OutCubic }
                    }
                }

                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 10

                    Text {
                        width: 18
                        text: modelData.icon
                        color: theme.textSecondary
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 14
                        horizontalAlignment: Text.AlignHCenter
                        textFormat: Text.PlainText
                    }

                    Text {
                        text: modelData.label
                        color: theme.textPrimary
                        font.pixelSize: 11
                        font.weight: Font.Medium
                        textFormat: Text.PlainText
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: 10
                    anchors.verticalCenter: parent.verticalCenter
                    width: 5
                    height: 5
                    radius: 3
                    visible: menu.currentMode === modelData.key
                    color: theme.accent
                    opacity: 0.82
                }

                MouseArea {
                    id: actionMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: menu.actionTriggered(modelData.key)
                }
            }
        }
    }
}
