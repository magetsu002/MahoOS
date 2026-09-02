import QtQuick
import Quickshell
import Quickshell.Widgets

Item {
    id: root

    required property var theme
    required property var backend
    required property var modelData
    required property int index
    property bool selected: false

    signal hovered(int index)
    signal activated(int index)

    readonly property bool pointerHovered: hover.hovered
    readonly property bool pressed: tap.pressed
    readonly property string requestedIcon: String(root.backend.iconName(root.modelData) || "")
    readonly property string resolvedIcon: {
        if (requestedIcon.length === 0)
            return ""
        if (requestedIcon.startsWith("/") || requestedIcon.startsWith("file://"))
            return requestedIcon
        return Quickshell.iconPath(requestedIcon, "")
    }
    readonly property bool hasIcon: resolvedIcon && resolvedIcon.length > 0
    readonly property string monogram: {
        const label = root.backend.displayName(root.modelData)
        return label && label.length > 0 ? label.slice(0, 1).toUpperCase() : "•"
    }

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
        scale: root.pressed ? 0.94 : (root.selected ? 1.035 : (root.pointerHovered ? 1.025 : 1))

        Behavior on scale { NumberAnimation { duration: 185; easing.type: Easing.OutBack } }

        Rectangle {
            anchors.fill: parent
            radius: 11
            color: root.selected
                ? theme.iconWellSelected
                : (root.pointerHovered ? theme.iconWellHover : theme.iconWellFill)
            border.width: 1
            border.color: root.selected ? theme.iconWellSelectedRim : theme.iconWellRim

            Behavior on color { ColorAnimation { duration: 170 } }
            Behavior on border.color { ColorAnimation { duration: 170 } }
        }

        IconImage {
            id: appIcon
            anchors.centerIn: parent
            width: 32
            height: 32
            source: root.resolvedIcon
            visible: root.hasIcon
            asynchronous: true
            mipmap: true
            smooth: true
            scale: root.selected ? 1.018 : (root.pointerHovered ? 1.01 : 1)
            Behavior on scale { NumberAnimation { duration: 175; easing.type: Easing.OutCubic } }
        }

        Text {
            anchors.centerIn: parent
            visible: !root.hasIcon
            text: root.monogram
            color: root.theme.alpha(root.theme.foreground, 0.86)
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 14
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
            text: root.backend.displayName(root.modelData)
            color: theme.textPrimary
            elide: Text.ElideRight
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 13
            font.weight: root.selected ? Font.DemiBold : Font.Medium
            renderType: Text.NativeRendering
        }

        Text {
            width: parent.width
            text: root.backend.displayDescription(root.modelData)
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

    // Hairline separation, intentionally quieter than the row content.
    Rectangle {
        anchors.left: iconWell.right
        anchors.leftMargin: 16
        anchors.right: parent.right
        anchors.rightMargin: 24
        anchors.bottom: parent.bottom
        height: 1
        radius: 1
        color: theme.divider
        opacity: root.selected ? 0.08 : (root.pointerHovered ? 0.24 : 0.36)

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
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: root.activated(root.index)
    }
}
