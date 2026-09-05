import QtQuick
import QtQuick.Effects

Item {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    property bool previewMode: false
    property bool pickerOpen: false
    property string pickerMode: "avatar"
    property real pickerProgress: pickerOpen ? 1 : 0
    property real avatarReveal: 0

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
        root.lockState.browseImages("")
    }

    function selectEntry(entry) {
        if (!entry)
            return

        const path = String(entry.path || "")
        if (path.length === 0)
            return

        if (entry.isDir === true) {
            root.lockState.browseImages(path)
            return
        }

        if (root.pickerMode === "avatar")
            root.lockState.setAvatar(path)
        else
            root.lockState.setLockWallpaper(path)

        root.pickerOpen = false
    }

    Component.onCompleted: avatarRevealTimer.start()

    Behavior on pickerProgress {
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }

    Behavior on avatarReveal {
        NumberAnimation { duration: 430; easing.type: Easing.OutCubic }
    }

    Timer {
        id: avatarRevealTimer
        interval: 240
        repeat: false
        onTriggered: root.avatarReveal = 1
    }

    MahoLockViewV5 {
        anchors.fill: parent
        theme: root.theme
        lockState: root.lockState
        auth: root.auth
        previewMode: root.previewMode
    }

    // Clicking the identity edits only the identity. Wallpaper customization has
    // a separate preview-only control so the two actions never share a menu.
    Item {
        id: avatarOverlay
        x: root.avatarX
        y: root.avatarY
        width: root.avatarSize
        height: root.avatarSize
        z: 40
        opacity: root.avatarReveal
        scale: (root.previewMode && avatarPointer.containsMouse ? 1.035 : 1)
            * (0.96 + root.avatarReveal * 0.04)

        Behavior on scale {
            NumberAnimation { duration: 155; easing.type: Easing.OutCubic }
        }

        Image {
            id: avatarRaw
            x: -2048
            y: -2048
            width: avatarOverlay.width
            height: avatarOverlay.height
            source: root.lockState.avatarUrl
            visible: root.lockState.avatarPath.length > 0
            fillMode: Image.PreserveAspectCrop
            smooth: true
            mipmap: true
            asynchronous: true
            cache: true
        }

        Rectangle {
            id: avatarMask
            x: -2048
            y: -2048
            width: avatarOverlay.width
            height: avatarOverlay.height
            radius: width / 2
            color: "white"
            visible: false
            layer.enabled: true
        }

        MultiEffect {
            anchors.fill: parent
            source: avatarRaw
            visible: root.lockState.avatarPath.length > 0 && avatarRaw.status === Image.Ready
            maskEnabled: true
            maskSource: avatarMask
        }

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: "transparent"
            border.width: Math.max(1, root.uiScale)
            border.color: Qt.rgba(
                1, 1, 1,
                root.previewMode && avatarPointer.containsMouse ? 0.34 : 0.18
            )
            visible: root.lockState.avatarPath.length > 0

            Behavior on border.color {
                ColorAnimation { duration: 135; easing.type: Easing.OutCubic }
            }
        }

        Rectangle {
            id: editBadge
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 1 * root.uiScale
            anchors.bottomMargin: 1 * root.uiScale
            width: 30 * root.uiScale
            height: width
            radius: width / 2
            visible: opacity > 0.001
            opacity: root.previewMode && avatarPointer.containsMouse ? 1 : 0
            color: Qt.rgba(0.08, 0.10, 0.14, 0.88)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.18)
            scale: avatarPointer.pressed ? 0.88 : 1

            Behavior on opacity {
                NumberAnimation { duration: 135; easing.type: Easing.OutCubic }
            }
            Behavior on scale {
                NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
            }

            MahoIconV2 {
                anchors.centerIn: parent
                width: 15 * root.uiScale
                height: 15 * root.uiScale
                name: "edit"
                iconOpacity: 0.93
            }
        }

        MouseArea {
            id: avatarPointer
            anchors.fill: parent
            enabled: root.previewMode && !root.pickerOpen
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openPicker("avatar")
        }
    }

    // Wallpaper customization is deliberately separate from the profile photo.
    Rectangle {
        id: wallpaperButton
        z: 42
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.uiScale
        width: 142 * root.uiScale
        height: 42 * root.uiScale
        radius: height / 2
        visible: root.previewMode && !root.pickerOpen
        color: wallpaperPointer.pressed
            ? Qt.rgba(1, 1, 1, 0.15)
            : (wallpaperPointer.containsMouse
                ? Qt.rgba(1, 1, 1, 0.11)
                : Qt.rgba(0.06, 0.075, 0.10, 0.52))
        border.width: 1
        border.color: wallpaperPointer.containsMouse
            ? Qt.rgba(1, 1, 1, 0.20)
            : Qt.rgba(1, 1, 1, 0.11)
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
                width: 17 * root.uiScale
                height: 17 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "wallpaper"
                iconOpacity: 0.90
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Wallpaper"
                color: Qt.rgba(1, 1, 1, 0.91)
                font.pixelSize: 12 * root.uiScale
                font.weight: Font.Medium
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

    // Native FileDialog windows can land underneath an Overlay-layer preview,
    // making the desktop appear frozen. Keep image selection inside the Maho
    // surface instead: no modal external window, no compositor-layer deadlock.
    MouseArea {
        anchors.fill: parent
        z: 70
        visible: root.pickerOpen || root.pickerProgress > 0.001
        enabled: visible
        onClicked: root.pickerOpen = false
    }

    Rectangle {
        id: pickerPanel
        z: 71
        anchors.centerIn: parent
        width: Math.min(root.width - 72 * root.uiScale, 860 * root.uiScale)
        height: Math.min(root.height - 92 * root.uiScale, 620 * root.uiScale)
        radius: 30 * root.uiScale
        visible: root.pickerOpen || root.pickerProgress > 0.001
        opacity: root.pickerProgress
        scale: 0.975 + root.pickerProgress * 0.025
        color: Qt.rgba(0.055, 0.070, 0.098, 0.94)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.16)
        clip: true

        transform: Translate {
            y: (1 - root.pickerProgress) * 12 * root.uiScale
        }

        MouseArea {
            anchors.fill: parent
            onClicked: function(mouse) { mouse.accepted = true }
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 26 * root.uiScale
            anchors.topMargin: 22 * root.uiScale
            text: root.pickerMode === "avatar"
                ? "Choose profile photo"
                : "Choose lock wallpaper"
            color: Qt.rgba(1, 1, 1, 0.97)
            font.pixelSize: 19 * root.uiScale
            font.weight: Font.DemiBold
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 26 * root.uiScale
            anchors.topMargin: 52 * root.uiScale
            text: root.pickerMode === "avatar"
                ? "Select an image from your files"
                : "Select a wallpaper independently from your profile photo"
            color: Qt.rgba(1, 1, 1, 0.60)
            font.pixelSize: 12 * root.uiScale
        }

        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 18 * root.uiScale
            anchors.topMargin: 18 * root.uiScale
            width: 34 * root.uiScale
            height: width
            radius: width / 2
            color: closePointer.containsMouse
                ? Qt.rgba(1, 1, 1, 0.10)
                : "transparent"

            Text {
                anchors.centerIn: parent
                text: "×"
                color: Qt.rgba(1, 1, 1, 0.82)
                font.pixelSize: 22 * root.uiScale
                font.weight: Font.Light
            }

            MouseArea {
                id: closePointer
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.pickerOpen = false
            }
        }

        Rectangle {
            id: pathBar
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.rightMargin: 24 * root.uiScale
            anchors.topMargin: 82 * root.uiScale
            height: 44 * root.uiScale
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.055)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.085)

            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 6 * root.uiScale
                width: 34 * root.uiScale
                height: width
                radius: width / 2
                visible: root.lockState.browserParent.length > 0
                color: upPointer.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.10)
                    : "transparent"

                MahoIconV2 {
                    anchors.centerIn: parent
                    width: 16 * root.uiScale
                    height: 16 * root.uiScale
                    name: "arrow-left"
                    iconOpacity: 0.86
                }

                MouseArea {
                    id: upPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.lockState.browseImages(root.lockState.browserParent)
                }
            }

            Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: (root.lockState.browserParent.length > 0 ? 48 : 16) * root.uiScale
                anchors.rightMargin: 16 * root.uiScale
                text: root.lockState.browserPath.length > 0
                    ? root.lockState.browserPath
                    : "Loading Pictures…"
                color: Qt.rgba(1, 1, 1, 0.70)
                font.pixelSize: 11 * root.uiScale
                elide: Text.ElideMiddle
            }
        }

        GridView {
            id: browserGrid
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: pathBar.bottom
            anchors.bottom: footer.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.rightMargin: 24 * root.uiScale
            anchors.topMargin: 16 * root.uiScale
            anchors.bottomMargin: 14 * root.uiScale
            clip: true
            model: root.lockState.browserEntries
            cellWidth: 154 * root.uiScale
            cellHeight: 128 * root.uiScale
            boundsBehavior: Flickable.StopAtBounds

            delegate: Item {
                required property int index
                property var entry: root.lockState.browserEntries[index] || ({})
                property bool isFolder: entry.isDir === true
                width: 142 * root.uiScale
                height: 116 * root.uiScale
                scale: entryPointer.pressed
                    ? 0.965
                    : (entryPointer.containsMouse ? 1.018 : 1)

                Behavior on scale {
                    NumberAnimation { duration: 115; easing.type: Easing.OutCubic }
                }

                Rectangle {
                    anchors.fill: parent
                    radius: 18 * root.uiScale
                    color: entryPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.105)
                        : Qt.rgba(1, 1, 1, 0.060)
                    border.width: 1
                    border.color: entryPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.18)
                        : Qt.rgba(1, 1, 1, 0.075)
                    clip: true

                    Image {
                        anchors.fill: parent
                        anchors.margins: 4 * root.uiScale
                        visible: !parent.parent.isFolder
                        source: !parent.parent.isFolder
                            ? encodeURI("file://" + String(parent.parent.entry.path || ""))
                            : ""
                        fillMode: Image.PreserveAspectCrop
                        smooth: true
                        mipmap: true
                        asynchronous: true
                        cache: true
                    }

                    Rectangle {
                        anchors.fill: parent
                        visible: parent.parent.isFolder
                        color: "transparent"

                        MahoIconV2 {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.top: parent.top
                            anchors.topMargin: 22 * root.uiScale
                            width: 38 * root.uiScale
                            height: 38 * root.uiScale
                            name: "folder"
                            iconOpacity: 0.82
                        }
                    }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 31 * root.uiScale
                        color: Qt.rgba(0.02, 0.025, 0.04, 0.72)

                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 9 * root.uiScale
                            anchors.rightMargin: 9 * root.uiScale
                            text: String(parent.parent.parent.entry.name || "")
                            color: Qt.rgba(1, 1, 1, 0.88)
                            font.pixelSize: 10.5 * root.uiScale
                            elide: Text.ElideRight
                        }
                    }
                }

                MouseArea {
                    id: entryPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.selectEntry(parent.entry)
                }
            }
        }

        Text {
            anchors.centerIn: browserGrid
            visible: root.lockState.browserPath.length > 0
                && root.lockState.browserEntries.length === 0
            text: "No image files in this folder"
            color: Qt.rgba(1, 1, 1, 0.52)
            font.pixelSize: 13 * root.uiScale
        }

        Item {
            id: footer
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 68 * root.uiScale

            Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 26 * root.uiScale
                text: "JPG · PNG · WEBP · AVIF · BMP"
                color: Qt.rgba(1, 1, 1, 0.42)
                font.pixelSize: 10 * root.uiScale
            }

            Rectangle {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 24 * root.uiScale
                width: root.pickerMode === "avatar"
                    ? 112 * root.uiScale
                    : 138 * root.uiScale
                height: 38 * root.uiScale
                radius: height / 2
                color: footerPointer.pressed
                    ? Qt.rgba(1, 1, 1, 0.16)
                    : (footerPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.12)
                        : Qt.rgba(1, 1, 1, 0.075))
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.11)

                Text {
                    anchors.centerIn: parent
                    text: root.pickerMode === "avatar"
                        ? "Use initials"
                        : "Shuffle"
                    color: Qt.rgba(1, 1, 1, 0.90)
                    font.pixelSize: 11.5 * root.uiScale
                    font.weight: Font.Medium
                }

                MouseArea {
                    id: footerPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (root.pickerMode === "avatar")
                            root.lockState.clearAvatar()
                        else
                            root.lockState.shuffleLockWallpaper()
                        root.pickerOpen = false
                    }
                }
            }
        }
    }
}
