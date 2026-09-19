import QtQuick

Rectangle {
    id: menu

    required property var theme
    property bool opened: false
    property bool dndEnabled: false
    property bool adaptiveQuiet: false
    property int heldCount: 0
    property int unreadCount: 0
    property int retainedCount: 0
    property int policyCount: 0

    signal dndToggleRequested()
    signal adaptiveStopRequested()
    signal reviewRequested()
    signal releaseRequested()
    signal markAllReadRequested()
    signal clearReadRequested()
    signal resetRulesRequested()

    width: 252
    implicitHeight: menuColumn.implicitHeight + 12
    radius: 13
    antialiasing: true
    color: theme.menuFill
    border.width: 1
    border.color: theme.menuRim
    visible: opened || opacity > 0.01
    opacity: opened ? 1 : 0
    scale: opened ? 1 : 0.985
    transformOrigin: Item.TopRight

    Behavior on opacity { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 12
        color: "transparent"
        border.width: 1
        border.color: theme.alpha(theme.foreground, 0.03)
    }

    Column {
        id: menuColumn
        x: 6
        y: 6
        width: parent.width - 12
        spacing: 2

        ControlRow {
            label: "Do Not Disturb"
            icon: "󰂛"
            trailing: menu.dndEnabled ? "On" : "Off"
            active: menu.dndEnabled
            onTriggered: menu.dndToggleRequested()
        }

        ControlRow {
            visible: menu.adaptiveQuiet
            height: visible ? 38 : 0
            label: "Stop Adaptive Focus"
            icon: "󰒲"
            trailing: "Active"
            active: true
            onTriggered: menu.adaptiveStopRequested()
        }

        Rectangle { width: parent.width; height: 1; color: menu.theme.divider; visible: menu.adaptiveQuiet }

        ControlRow {
            label: "Review held"
            icon: "󰋚"
            trailing: menu.heldCount > 0 ? String(menu.heldCount) : ""
            enabled: menu.heldCount > 0
            onTriggered: menu.reviewRequested()
        }

        ControlRow {
            label: "Release held now"
            icon: "󰐊"
            enabled: menu.heldCount > 0
            onTriggered: menu.releaseRequested()
        }

        Rectangle { width: parent.width; height: 1; color: menu.theme.divider }

        ControlRow {
            label: "Mark all as read"
            icon: "󰄬"
            trailing: menu.unreadCount > 0 ? String(menu.unreadCount) : ""
            enabled: menu.unreadCount > 0
            onTriggered: menu.markAllReadRequested()
        }

        ControlRow {
            label: "Clear read history"
            icon: "󰆴"
            enabled: menu.retainedCount > menu.unreadCount
            onTriggered: menu.clearReadRequested()
        }

        ControlRow {
            label: "Reset app rules"
            icon: "󰒓"
            trailing: menu.policyCount > 0 ? String(menu.policyCount) : ""
            enabled: menu.policyCount > 0
            onTriggered: menu.resetRulesRequested()
        }
    }

    component ControlRow: Rectangle {
        id: control
        required property string label
        required property string icon
        property string trailing: ""
        property bool active: false
        signal triggered()

        width: menuColumn.width
        height: 38
        radius: 9
        opacity: enabled ? 1 : 0.42
        color: controlMouse.pressed
            ? menu.theme.menuPressed
            : (controlMouse.containsMouse ? menu.theme.menuHover : "transparent")

        Behavior on color { ColorAnimation { duration: 105; easing.type: Easing.OutCubic } }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 20
            text: control.icon
            color: control.active ? menu.theme.accent : menu.theme.textSecondary
            font.family: "JetBrainsMono Nerd Font"
            font.pixelSize: 13
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 40
            anchors.right: trailingText.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: control.label
            color: menu.theme.textPrimary
            font.pixelSize: 11
            font.weight: Font.Medium
            elide: Text.ElideRight
            textFormat: Text.PlainText
        }

        Text {
            id: trailingText
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: control.trailing
            color: control.active ? menu.theme.accent : menu.theme.textFaint
            font.pixelSize: 10
            font.weight: Font.Medium
            textFormat: Text.PlainText
        }

        MouseArea {
            id: controlMouse
            anchors.fill: parent
            enabled: control.enabled
            hoverEnabled: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: control.triggered()
        }
    }
}
