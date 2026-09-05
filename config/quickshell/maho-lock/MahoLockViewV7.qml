import QtQuick

Item {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    property bool surfaceReady: false
    property bool previewMode: false
    property bool pickerOpen: false
    property string pickerMode: "avatar"
    property real avatarReveal: 0

    readonly property bool presentationReady:
        surfaceReady && width > 0 && height > 0

    readonly property real uiScale: Math.max(
        0.78,
        Math.min(1.18, Math.min(width / 1600, height / 1000))
    )
    readonly property real mainY: Math.max(158 * uiScale, height * 0.17)
    readonly property real avatarSize: 112 * uiScale
    readonly property real avatarX: (width - avatarSize) / 2
    readonly property real avatarY: mainY + 322 * uiScale

    function openPicker(mode) {
        if (!root.previewMode)
            return
        root.pickerMode = mode
        root.pickerOpen = true
    }

    function activatePresentation() {
        if (!presentationReady)
            return

        avatarReveal = 1
    }

    function requestPasswordFocus() {
        baseView.reclaimPasswordFocus()
    }

    onPresentationReadyChanged: activatePresentation()
    Component.onCompleted: activatePresentation()

    Behavior on avatarReveal {
        NumberAnimation { duration: 430; easing.type: Easing.OutCubic }
    }

    MahoLockViewV5 {
        id: baseView
        anchors.fill: parent
        theme: root.theme
        lockState: root.lockState
        auth: root.auth
        surfaceReady: root.presentationReady
        previewMode: root.previewMode
    }

    MahoAvatarControl {
        id: avatarControl
        x: root.avatarX
        y: root.avatarY
        width: root.avatarSize
        height: root.avatarSize
        z: 40
        opacity: root.avatarReveal
        theme: root.theme
        lockState: root.lockState
        uiScale: root.uiScale
        editable: root.previewMode && !root.pickerOpen
        onEditRequested: root.openPicker("avatar")
    }

    // Wallpaper has its own distinct affordance; the profile photo never opens it.
    Rectangle {
        id: wallpaperButton
        z: 42
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.uiScale
        width: 146 * root.uiScale
        height: 42 * root.uiScale
        radius: height / 2
        antialiasing: true
        visible: root.previewMode && !root.pickerOpen
        color: wallpaperPointer.pressed
            ? Qt.rgba(1, 1, 1, 0.15)
            : (wallpaperPointer.containsMouse
                ? Qt.rgba(1, 1, 1, 0.11)
                : Qt.rgba(0.06, 0.075, 0.10, 0.56))
        border.width: 1
        border.color: wallpaperPointer.containsMouse
            ? Qt.rgba(1, 1, 1, 0.20)
            : Qt.rgba(1, 1, 1, 0.14)
        scale: wallpaperPointer.pressed ? 0.975 : 1

        Behavior on color { ColorAnimation { duration: 125 } }
        Behavior on border.color { ColorAnimation { duration: 125 } }
        Behavior on scale {
            NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
        }

        Row {
            anchors.centerIn: parent
            spacing: 8 * root.uiScale

            MahoIconV2 {
                width: 18 * root.uiScale
                height: 18 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "wallpaper"
                iconOpacity: 0.92
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Wallpaper"
                color: Qt.rgba(1, 1, 1, 0.93)
                font.pixelSize: 12 * root.uiScale
                font.family: baseView.uiFontFamily
                font.weight: baseView.useRoundedTypography
                    ? Font.DemiBold
                    : Font.Medium
                font.variableAxes: ({
                    "wght": baseView.useRoundedTypography ? 700 : 500
                })
                style: Text.Raised
                styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.18)
            }
        }

        MouseArea {
            id: wallpaperPointer
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openPicker("wallpaper")
        }
    }

    MahoImagePicker {
        anchors.fill: parent
        z: 70
        lockState: root.lockState
        open: root.pickerOpen
        mode: root.pickerMode
        uiScale: root.uiScale
        onCloseRequested: root.pickerOpen = false
        onImageSelected: function(path) {
            if (root.pickerMode === "avatar")
                root.lockState.setAvatar(path)
            else
                root.lockState.setLockWallpaper(path)
            root.pickerOpen = false
        }
    }
}
