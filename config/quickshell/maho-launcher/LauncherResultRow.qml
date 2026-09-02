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
    readonly property string resolvedIcon: requestedIcon.length > 0
        ? Quickshell.iconPath(requestedIcon, "")
        : ""
    readonly property bool hasIcon: resolvedIcon && resolvedIcon.length > 0
    readonly property string monogram: {
        const label = root.backend.displayName(root.modelData)
        return label && label.length > 0 ? label.slice(0, 1).toUpperCase() : "•"
    }

    height: 58
    scale: pressed ? 0.993 : 1

    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 2
        radius: 14
        color: root.pointerHovered && !root.selected ? theme.rowHover : "transparent"
        border.width: 1
        border.color: root.pointerHovered && !root.selected ? theme.rowHoverRim : "transparent"

        Behavior on color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
        Behavior on border.color { ColorAnimation { duration: 145; easing.type: Easing.OutCubic } }
    }

    Item {
        id: iconWell
        anchors.left: parent.left
        anchors.leftMargin: 15
        anchors.verticalCenter: parent.verticalCenter
        width: 40
        height: 40
        scale: root.pressed ? 0.94 : (root.selected ? 1.035 : (root.pointerHovered ? 1.022 : 1))

        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }

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
            scale: root.selected ? 1.015 : 1
            Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
        }

        Text {
            anchors.centerIn: parent
            visible: !root.hasIcon
            text: root.monogram
            color: root.theme.alpha(root.theme.foreground, 0.88)
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
        anchors.rightMargin: 14
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
        anchors.rightMargin: 17
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -1
        text: "›"
        color: root.selected
            ? theme.alpha(theme.foreground, 0.88)
            : theme.alpha(theme.muted, root.pointerHovered ? 0.76 : 0.50)
        font.family: "Inter, Noto Sans, sans-serif"
        font.pixelSize: 19
        font.weight: Font.Medium
        x: root.pointerHovered || root.selected ? 3 : 0

        Behavior on color { ColorAnimation { duration: 145 } }
        Behavior on x { NumberAnimation { duration: 155; easing.type: Easing.OutCubic } }
    }

    // Premium inset separator: deliberately low contrast and aligned with the
    // content rather than touching the app icon or container edges.
    Rectangle {
        anchors.left: iconWell.right
        anchors.leftMargin: 14
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.bottom: parent.bottom
        height: 1
        color: theme.divider
        opacity: root.selected ? 0.20 : (root.pointerHovered ? 0.58 : 0.78)

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
