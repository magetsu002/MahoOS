import QtQuick
import QtQuick.Effects

Item {
    id: root

    required property var theme
    required property var lockState
    property bool editable: false
    property real uiScale: 1
    property bool hovered: pointer.containsMouse
    signal editRequested()

    readonly property real avatarRadius: width / 2
    readonly property real badgeSize: 30 * uiScale
    readonly property real badgeRadius: badgeSize / 2

    // Exact geometry: the badge center lies on the avatar circumference at 45°.
    // For a circle radius R, x/y offset = R / sqrt(2).
    readonly property real badgeCenterOffset: avatarRadius / Math.SQRT2
    readonly property real badgeCenterX: width / 2 + badgeCenterOffset
    readonly property real badgeCenterY: height / 2 + badgeCenterOffset
    readonly property int avatarDecodeSize: Math.max(1024, Math.ceil(width * 6))

    scale: editable && hovered ? 1.035 : 1

    Behavior on scale {
        NumberAnimation { duration: 155; easing.type: Easing.OutCubic }
    }

    Rectangle {
        id: avatarHalo
        anchors.fill: parent
        radius: width / 2
        antialiasing: true
        color: Qt.rgba(0.490, 0.804, 1.000, 0.14)
        border.width: Math.max(1, root.uiScale)
        border.color: Qt.rgba(0.882, 0.961, 1.000, 0.68)
        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowOpacity: 0.20
            shadowBlur: 0.78
            shadowHorizontalOffset: 0
            shadowVerticalOffset: 5
            shadowColor: Qt.rgba(0.020, 0.118, 0.255, 0.80)
            blurMax: 24
        }
    }

    Rectangle {
        anchors.fill: parent
        anchors.margins: 5 * root.uiScale
        radius: width / 2
        antialiasing: true
        color: root.theme.alpha(
            root.theme.mix(root.theme.accent, Qt.rgba(0.35, 0.45, 0.98, 1), 0.34),
            0.88
        )
        border.width: Math.max(1, root.uiScale)
        border.color: Qt.rgba(1, 1, 1, 0.23)
    }

    Text {
        anchors.fill: parent
        z: 4
        visible: root.lockState.avatarPath.length === 0
        text: root.lockState.displayName.length > 0
            ? root.lockState.displayName.charAt(0).toUpperCase()
            : "M"
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: Qt.rgba(1, 1, 1, 0.985)
        font.pixelSize: 44 * root.uiScale
        font.weight: Font.Light
        renderType: Text.NativeRendering
    }

    Image {
        id: avatarRaw
        x: -4096
        y: -4096
        width: root.width
        height: root.height
        source: root.lockState.avatarUrl
        visible: root.lockState.avatarPath.length > 0
        fillMode: Image.PreserveAspectCrop
        smooth: true
        mipmap: true
        asynchronous: true
        cache: true
        sourceSize.width: root.avatarDecodeSize
        sourceSize.height: root.avatarDecodeSize
    }

    Rectangle {
        id: avatarMask
        x: -4096
        y: -4096
        width: root.width
        height: root.height
        radius: width / 2
        antialiasing: true
        color: "white"
        visible: false
        layer.enabled: true
    }

    MultiEffect {
        anchors.fill: parent
        z: 5
        source: avatarRaw
        visible: root.lockState.avatarPath.length > 0 && avatarRaw.status === Image.Ready
        maskEnabled: true
        maskSource: avatarMask
    }

    Rectangle {
        anchors.fill: parent
        z: 6
        radius: width / 2
        antialiasing: true
        color: "transparent"
        border.width: Math.max(1, root.uiScale)
        border.color: Qt.rgba(
            0.882, 0.961, 1.000,
            root.editable && root.hovered ? 0.78 : 0.62
        )

        Behavior on border.color {
            ColorAnimation { duration: 135; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        id: editBadge
        z: 8
        x: root.badgeCenterX - width / 2
        y: root.badgeCenterY - height / 2
        width: root.badgeSize
        height: root.badgeSize
        radius: width / 2
        antialiasing: true
        visible: opacity > 0.001
        opacity: root.editable && root.hovered ? 1 : 0
        color: Qt.rgba(0.08, 0.10, 0.14, 0.90)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.19)
        scale: pointer.pressed ? 0.88 : 1

        Behavior on opacity {
            NumberAnimation { duration: 135; easing.type: Easing.OutCubic }
        }
        Behavior on scale {
            NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
        }

        MahoIconV2 {
            anchors.centerIn: parent
            width: 16 * root.uiScale
            height: 16 * root.uiScale
            name: "edit"
            iconOpacity: 0.95
        }
    }

    MouseArea {
        id: pointer
        anchors.fill: parent
        enabled: root.editable
        hoverEnabled: true
        cursorShape: root.editable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.editRequested()
    }
}
