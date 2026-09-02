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

    height: 58
    scale: pressed ? 0.992 : 1

    Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 1
        radius: 13
        color: root.pointerHovered && !root.selected ? theme.rowHover : "transparent"
        border.width: 1
        border.color: root.pointerHovered && !root.selected
            ? theme.alpha(theme.outline, 0.055)
            : "transparent"

        Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
        Behavior on border.color { ColorAnimation { duration: 135 } }
    }

    Item {
        id: iconWell
        anchors.left: parent.left
        anchors.leftMargin: 15
        anchors.verticalCenter: parent.verticalCenter
        width: 38
        height: 38
        scale: root.selected ? 1.025 : (root.pointerHovered ? 1.015 : 1)

        Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutBack } }

        Rectangle {
            anchors.fill: parent
            radius: 10
            color: root.selected
                ? theme.alpha(theme.accent, 0.055)
                : theme.alpha(theme.foreground, 0.018)
            border.width: 1
            border.color: root.selected
                ? theme.alpha(theme.accent, 0.10)
                : theme.alpha(theme.outline, 0.040)

            Behavior on color { ColorAnimation { duration: 170 } }
            Behavior on border.color { ColorAnimation { duration: 170 } }
        }

        IconImage {
            id: appIcon
            anchors.centerIn: parent
            width: 30
            height: 30
            source: {
                const requested = root.backend.iconName(root.modelData)
                const resolved = Quickshell.iconPath(requested, true)
                if (resolved && resolved.length > 0)
                    return resolved
                const fallback = root.backend.mode === 1
                    ? (root.modelData.kind === "directory" ? "folder" : "text-x-generic")
                    : "application-x-executable"
                return Quickshell.iconPath(fallback, true)
            }
            asynchronous: true
            mipmap: true
            smooth: true
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

            Behavior on color { ColorAnimation { duration: 140 } }
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
        text: "›"
        color: root.selected
            ? theme.alpha(theme.foreground, 0.84)
            : theme.alpha(theme.muted, root.pointerHovered ? 0.72 : 0.46)
        font.family: "Inter, Noto Sans, sans-serif"
        font.pixelSize: 19
        font.weight: Font.Medium
        x: root.pointerHovered || root.selected ? 2 : 0

        Behavior on color { ColorAnimation { duration: 140 } }
        Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
    }

    Rectangle {
        anchors.left: iconWell.right
        anchors.leftMargin: 14
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.bottom: parent.bottom
        height: 1
        color: theme.divider
        opacity: root.selected ? 0.22 : 0.72

        Behavior on opacity { NumberAnimation { duration: 140 } }
    }

    HoverHandler {
        id: hover
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
