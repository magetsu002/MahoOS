import QtQuick
import QtQuick.Effects

Item {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    property bool previewMode: false
    property bool profileOpen: false
    property real profileProgress: profileOpen ? 1 : 0
    property real avatarReveal: 0

    readonly property real uiScale: Math.max(
        0.78,
        Math.min(1.18, Math.min(width / 1600, height / 1000))
    )
    readonly property real mainY: Math.max(158 * uiScale, height * 0.17)
    readonly property real avatarSize: 112 * uiScale
    readonly property real avatarX: (width - avatarSize) / 2
    readonly property real avatarY: mainY + 322 * uiScale

    Component.onCompleted: avatarRevealTimer.start()

    Behavior on profileProgress {
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

    // The profile-photo layer is additive so the accepted V5 lock composition
    // remains unchanged. Editing is preview-only; the real lock never exposes
    // unauthenticated appearance mutation.
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
            opacity: root.previewMode && (avatarPointer.containsMouse || root.profileOpen) ? 1 : 0
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
            enabled: root.previewMode
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                root.profileOpen = !root.profileOpen
                if (root.profileOpen)
                    root.lockState.refreshAvatarCandidates()
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        z: 48
        visible: root.profileOpen || root.profileProgress > 0.001
        enabled: visible
        onClicked: root.profileOpen = false
    }

    Rectangle {
        id: profilePanel
        z: 50
        visible: root.profileOpen || root.profileProgress > 0.001
        width: 452 * root.uiScale
        height: 366 * root.uiScale
        radius: 28 * root.uiScale
        x: Math.min(
            root.width - width - 34 * root.uiScale,
            root.width / 2 + 175 * root.uiScale
        )
        y: Math.max(88 * root.uiScale, root.avatarY - 104 * root.uiScale)
        color: Qt.rgba(0.072, 0.087, 0.118, 0.88)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.17)
        opacity: root.profileProgress
        scale: 0.965 + root.profileProgress * 0.035

        transform: Translate {
            y: (1 - root.profileProgress) * 10 * root.uiScale
        }

        MouseArea {
            anchors.fill: parent
            onClicked: function(mouse) { mouse.accepted = true }
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.topMargin: 22 * root.uiScale
            text: "Personalize"
            color: Qt.rgba(1, 1, 1, 0.97)
            font.pixelSize: 18 * root.uiScale
            font.weight: Font.DemiBold
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.topMargin: 52 * root.uiScale
            text: root.lockState.avatarCandidates.length > 0
                ? "Choose a profile photo or shuffle the lock wallpaper"
                : "Add photos to ~/Pictures/Avatars or ~/Pictures/Profile"
            color: Qt.rgba(1, 1, 1, 0.62)
            font.pixelSize: 12 * root.uiScale
        }

        Grid {
            id: avatarGrid
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.topMargin: 88 * root.uiScale
            columns: 4
            rowSpacing: 12 * root.uiScale
            columnSpacing: 12 * root.uiScale

            Repeater {
                model: Math.min(8, root.lockState.avatarCandidates.length)

                Item {
                    required property int index
                    width: 86 * root.uiScale
                    height: width
                    property string path: String(root.lockState.avatarCandidates[index] || "")
                    property bool selected: path.length > 0 && path === root.lockState.avatarPath
                    scale: candidatePointer.pressed
                        ? 0.94
                        : (candidatePointer.containsMouse ? 1.035 : 1)

                    Behavior on scale {
                        NumberAnimation { duration: 130; easing.type: Easing.OutCubic }
                    }

                    Rectangle {
                        anchors.fill: parent
                        radius: 19 * root.uiScale
                        color: Qt.rgba(
                            1, 1, 1,
                            parent.selected ? 0.145 : (candidatePointer.containsMouse ? 0.12 : 0.070)
                        )
                        border.width: parent.selected ? 2 : 1
                        border.color: parent.selected
                            ? Qt.rgba(1, 1, 1, 0.42)
                            : (candidatePointer.containsMouse
                                ? Qt.rgba(1, 1, 1, 0.27)
                                : Qt.rgba(1, 1, 1, 0.10))

                        Behavior on color { ColorAnimation { duration: 120 } }
                        Behavior on border.color { ColorAnimation { duration: 120 } }
                    }

                    Image {
                        anchors.fill: parent
                        anchors.margins: 5 * root.uiScale
                        source: parent.path.length > 0
                            ? encodeURI("file://" + parent.path)
                            : ""
                        fillMode: Image.PreserveAspectCrop
                        smooth: true
                        mipmap: true
                        asynchronous: true
                        cache: true
                    }

                    MouseArea {
                        id: candidatePointer
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.lockState.setAvatar(parent.path)
                            root.profileOpen = false
                        }
                    }
                }
            }
        }

        Row {
            anchors.left: parent.left
            anchors.bottom: parent.bottom
            anchors.leftMargin: 24 * root.uiScale
            anchors.bottomMargin: 20 * root.uiScale
            spacing: 9 * root.uiScale

            Rectangle {
                width: 112 * root.uiScale
                height: 39 * root.uiScale
                radius: height / 2
                color: initialsPointer.pressed
                    ? Qt.rgba(1, 1, 1, 0.17)
                    : (initialsPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.14)
                        : Qt.rgba(1, 1, 1, 0.09))
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.13)
                scale: initialsPointer.pressed ? 0.97 : 1

                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }

                Text {
                    anchors.centerIn: parent
                    text: "Use initials"
                    color: Qt.rgba(1, 1, 1, 0.92)
                    font.pixelSize: 12 * root.uiScale
                }

                MouseArea {
                    id: initialsPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.lockState.clearAvatar()
                        root.profileOpen = false
                    }
                }
            }

            Rectangle {
                width: 128 * root.uiScale
                height: 39 * root.uiScale
                radius: height / 2
                color: wallpaperPointer.pressed
                    ? Qt.rgba(1, 1, 1, 0.17)
                    : (wallpaperPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.14)
                        : Qt.rgba(1, 1, 1, 0.09))
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.13)
                scale: wallpaperPointer.pressed ? 0.97 : 1

                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }

                Text {
                    anchors.centerIn: parent
                    text: "New wallpaper"
                    color: Qt.rgba(1, 1, 1, 0.92)
                    font.pixelSize: 12 * root.uiScale
                }

                MouseArea {
                    id: wallpaperPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.lockState.chooseLockWallpaper()
                }
            }

            Rectangle {
                width: 96 * root.uiScale
                height: 39 * root.uiScale
                radius: height / 2
                color: refreshPointer.pressed
                    ? Qt.rgba(1, 1, 1, 0.17)
                    : (refreshPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.14)
                        : Qt.rgba(1, 1, 1, 0.09))
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.13)
                scale: refreshPointer.pressed ? 0.97 : 1

                Behavior on scale {
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }

                Text {
                    anchors.centerIn: parent
                    text: "Refresh"
                    color: Qt.rgba(1, 1, 1, 0.92)
                    font.pixelSize: 12 * root.uiScale
                }

                MouseArea {
                    id: refreshPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.lockState.refreshAvatarCandidates()
                }
            }
        }
    }
}
