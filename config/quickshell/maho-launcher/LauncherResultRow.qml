import QtQuick
import Quickshell

Item {
    id: root

    // The explicit theme role avoids the old self-binding ambiguity while the
    // delegate emits only an index for authoritative parent-side activation.
    required property var theme
    required property int index
    required property string entryId
    required property string name
    required property string description
    required property string icon
    required property string iconPath
    required property string path
    required property string kind
    property bool selected: false

    signal hovered(int index)
    signal activated(int index)

    LauncherTheme { id: fallbackPalette }

    readonly property var palette: root.theme || fallbackPalette
    readonly property bool pointerHovered: hover.hovered
    readonly property bool pressed: tap.pressed

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
        color: root.pointerHovered && !root.selected ? root.palette.rowHover : "transparent"
        border.width: 1
        border.color: root.pointerHovered && !root.selected ? root.palette.rowHoverRim : "transparent"

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

        // Real application artwork only. Missing artwork leaves transparent
        // space rather than synthesizing a cheap tile or letter placeholder.
        LauncherAppIcon {
            anchors.centerIn: parent
            width: 36
            height: 36
            name: root.name
            entryId: root.entryId
            icon: root.icon
            iconPath: root.iconPath
            scale: root.selected ? 1.012 : (root.pointerHovered ? 1.008 : 1)

            Behavior on scale { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
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
            color: root.palette.textPrimary
            opacity: root.selected ? 1 : 0.96
            elide: Text.ElideRight
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 14
            font.weight: root.selected ? Font.DemiBold : Font.Medium
            renderType: Text.NativeRendering

            Behavior on opacity { NumberAnimation { duration: 140 } }
        }

        Text {
            width: parent.width
            text: root.description
            color: root.palette.textSecondary
            opacity: root.selected ? 0.92 : 0.84
            elide: Text.ElideRight
            font.family: "Inter, Noto Sans, sans-serif"
            font.pixelSize: 11
            renderType: Text.NativeRendering

            Behavior on opacity { NumberAnimation { duration: 140 } }
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
            ? root.palette.alpha(root.palette.foreground, 0.82)
            : root.palette.alpha(root.palette.muted, root.pointerHovered ? 0.66 : 0.38)
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
        color: root.palette.divider
        opacity: root.selected ? 0.05 : (root.pointerHovered ? 0.14 : 0.20)

        Behavior on opacity { NumberAnimation { duration: 145 } }
    }

    HoverHandler {
        id: hover
        cursorShape: Qt.PointingHandCursor
        onHoveredChanged: {
            if (hovered)
                root.hovered(root.index)
        }
        onPointChanged: {
            if (hovered)
                root.hovered(root.index)
        }
    }

    TapHandler {
        id: tap
        acceptedButtons: Qt.LeftButton
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: {
            root.hovered(root.index)
            root.activated(root.index)
        }
    }
}
