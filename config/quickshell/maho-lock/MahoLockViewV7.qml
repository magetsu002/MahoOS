import QtQuick

Item {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    property bool surfaceReady: false
    property bool previewMode: false
    property bool pickerOpen: false

    readonly property bool presentationReady:
        surfaceReady && width > 0 && height > 0

    readonly property real uiScale: Math.max(
        0.78,
        Math.min(1.18, Math.min(width / 1600, height / 1000))
    )

    function openWallpaperPicker() {
        if (!root.previewMode)
            return
        root.pickerOpen = true
    }

    function requestPasswordFocus() {
        baseView.reclaimPasswordFocus()
    }

    MahoLockViewV5 {
        id: baseView
        anchors.fill: parent
        theme: root.theme
        lockState: root.lockState
        auth: root.auth
        surfaceReady: root.presentationReady
        previewMode: root.previewMode
        suppressBuiltinAvatar: true
    }

    // Wallpaper has its own distinct affordance; the profile photo never opens it.
    Rectangle {
        id: wallpaperButton
        z: 42
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.uiScale
        width: 176 * root.uiScale
        height: 52 * root.uiScale
        radius: height / 2
        antialiasing: true
        visible: root.previewMode && !root.pickerOpen
        color: wallpaperPointer.pressed
            ? Qt.rgba(1, 1, 1, 0.15)
            : (wallpaperPointer.containsMouse
                ? Qt.rgba(1, 1, 1, 0.11)
                : Qt.rgba(0.031, 0.106, 0.227, 0.23))
        border.width: 1
        border.color: wallpaperPointer.containsMouse
            ? Qt.rgba(1, 1, 1, 0.20)
            : Qt.rgba(0.90, 0.97, 1.0, 0.20)
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
            onClicked: root.openWallpaperPicker()
        }
    }

    MahoImagePicker {
        anchors.fill: parent
        z: 70
        lockState: root.lockState
        open: root.pickerOpen
        mode: "wallpaper"
        uiScale: root.uiScale
        onCloseRequested: root.pickerOpen = false
        onImageSelected: function(path) {
            root.lockState.setLockWallpaper(path)
            root.pickerOpen = false
        }
    }
}
