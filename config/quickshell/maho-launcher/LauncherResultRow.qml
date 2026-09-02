import QtQuick
import Quickshell
import Quickshell.Widgets

Item {
    id: root

    required property var theme
    required property var backend
    required property int index
    required property string name
    required property string description
    required property string icon
    required property string iconPath
    property bool selected: false

    signal hovered(int index)
    signal activated(int index)

    readonly property bool pointerHovered: hover.hovered
    readonly property bool pressed: tap.pressed
    readonly property string requestedIcon: iconPath.length > 0 ? iconPath : icon
    readonly property string resolvedIcon: {
        if (requestedIcon.length === 0)
            return ""
        if (requestedIcon.startsWith("/") || requestedIcon.startsWith("file://"))
            return requestedIcon
        return Quickshell.iconPath(requestedIcon, "")
    }
    readonly property bool hasIcon: resolvedIcon && resolvedIcon.length > 0
    readonly property bool iconReady: root.hasIcon && appIcon.status === Image.Ready
    readonly property string monogram: name.length > 0 ? name.slice(0, 1).toUpperCase() : "•"
    property var modelData: root.backend.itemAt(root.index)

    height: 58
    x: root.pointerHovered && !root.selected ? 2 : 0
    scale: pressed ? 0.994 : 1

    Behavior on x { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        anchors.leftMargin: 3
        anchors.rightMargin: 3
        anchors.topMargin: 2
        anchors.bottomMargin: 2
        radius: 14
        antialiasing: true
        color: root.pointerHovered && !root.selected ? theme.rowHover : "transparent"
        border.width: 1
        border.color: root.pointerHovered && !root.selected ? theme.rowHoverRim : "transparent"

        Behavior on color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }
        Behavior on border.color { ColorAnimation { duration: 155; easing.type: Easing.OutCubic } }
    }

    Item {
        id: iconWell
        anchors.left: parent.left
        anchors.leftMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        width: 40
        height: 40
        scale: root.pressed ? 0.94 : (root.selected ? 1.025 : (root.pointerHovered ? 1.018 : 1))

        Behavior on scale { NumberAnimation { duration: 175; easing.type: Easing.OutCubic } }

        Rectangle {
            anchors.fill: parent
            radius: 11
            antialiasing: true
            color: root.selected
                ? theme.iconWellSelected
                : (root.pointerHovered ? theme.iconWellHover : theme.iconWellFill)
            border.width: root.selected || root.pointerHovered ? 1 : 0
            border.color: root.selected ? theme.iconWellSelectedRim : theme.iconWellRim

            Behavior on color { ColorAnimation { duration: 165 } }
            Behavior on border.color { ColorAnimation { duration: 165 } }
        }

        IconImage {
            id: appIcon
            anchors.centerIn: parent
            width: 34
            height: 34
            source: root.resolvedIcon
            visible: root.iconReady
            asynchronous: true
            mipmap: true
            smooth: true
            scale: root.selected ? 1.012 : (root.pointerHovered ? 1.008 : 1)
            Behavior on scale { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
        }

        // A non-empty icon path is not proof that Qt could render the artwork.
        // Keep a restrained text fallback until Image.Ready so broken symbolic
        // or unsupported assets never become blank white application tiles.
        Text {
            anchors.centerIn: parent
            visible: !root.iconReady
            text: root.monogram
            color: root.theme.alpha(root.theme.foreground, 0.72)
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 15
            font.weight: Font.DemiBold
            renderType: Text.NativeRendering
        }
    }

    Column {
        anchors.left: iconWell.right
        anchors.leftMargin: 14
        anchors.right: chevron.left
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        spacing: 3

        Text {
            width: parent.width
            text: root.name
            color: theme.textPrimary
            elide: Text.ElideRight
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 13
            font.weight: root.selected ? Font.DemiBold : Font.Medium
            renderType: Text.NativeRendering
        }

        Text {
            width: parent.width
            text: root.description
            color: theme.textSecondary
            elide: Text.ElideRight
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 10
            renderType: Text.NativeRendering
        }
    }

    Text {
        id: chevron
        anchors.right: parent.right
        anchors.rightMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -1
        text: "›"
        color: root.selected
            ? theme.alpha(theme.foreground, 0.82)
            : theme.alpha(theme.muted, root.pointerHovered ? 0.66 : 0.38)
        font.family: "Inter, Noto Sans, sans-serif"
        font.pixelSize: 18
        font.weight: Font.Medium
        x: root.pointerHovered || root.selected ? 3 : 0

        Behavior on color { ColorAnimation { duration: 145 } }
        Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    }

    Rectangle {
        anchors.left: iconWell.right
        anchors.leftMargin: 16
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.bottom: parent.bottom
        height: 1
        radius: 1
        color: theme.divider
        opacity: root.selected ? 0.05 : (root.pointerHovered ? 0.18 : 0.28)

        Behavior on opacity { NumberAnimation { duration: 145 } }
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
        onHoveredChanged: {
            if (hovered)
                root.hovered(root.index)
        }
    }

    TapHandler {
        id: tap
        acceptedButtons: Qt.LeftButton
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.activated(root.index)
    }
}
