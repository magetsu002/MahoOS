import QtQuick
import QtQuick.Effects

Item {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    property bool previewMode: false
    property bool profileOpen: false

    readonly property real uiScale: Math.max(
        0.78,
        Math.min(1.18, Math.min(width / 1600, height / 1000))
    )
    readonly property real mainY: Math.max(158 * uiScale, height * 0.17)
    readonly property real avatarSize: 112 * uiScale
    readonly property real avatarX: (width - avatarSize) / 2
    readonly property real avatarY: mainY + 322 * uiScale

    MahoLockViewV5 {
        anchors.fill: parent
        theme: root.theme
        lockState: root.lockState
        auth: root.auth
        previewMode: root.previewMode
    }

    // Profile-photo overlay deliberately lives above the accepted V5 layout so
    // the lock hierarchy stays stable. Editing is available only in safe preview
    // mode; unauthenticated users cannot mutate profile state from a real lock.
    Item {
        id: avatarOverlay
        x: root.avatarX
        y: root.avatarY
        width: root.avatarSize
        height: root.avatarSize
        z: 40

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
            border.color: Qt.rgba(1, 1, 1, root.previewMode && avatarPointer.containsMouse ? 0.32 : 0.18)
            visible: root.lockState.avatarPath.length > 0

            Behavior on border.color {
                ColorAnimation { duration: 140; easing.type: Easing.OutCubic }
            }
        }

        Rectangle {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 1 * root.uiScale
            anchors.bottomMargin: 1 * root.uiScale
            width: 30 * root.uiScale
            height: width
            radius: width / 2
            visible: root.previewMode && (avatarPointer.containsMouse || root.profileOpen)
            color: Qt.rgba(0.08, 0.10, 0.14, 0.86)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.17)
            scale: avatarPointer.pressed ? 0.90 : 1

            Behavior on opacity { NumberAnimation { duration: 130 } }
            Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

            MahoIconV2 {
                anchors.centerIn: parent
                width: 15 * root.uiScale
                height: 15 * root.uiScale
                name: "edit"
                iconOpacity: 0.92
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
        visible: root.profileOpen
        enabled: visible
        onClicked: root.profileOpen = false
    }

    Rectangle {
        id: profilePanel
        z: 50
        visible: root.profileOpen
        width: 430 * root.uiScale
        height: 350 * root.uiScale
        radius: 27 * root.uiScale
        x: Math.min(
            root.width - width - 34 * root.uiScale,
            root.width / 2 + 175 * root.uiScale
        )
        y: Math.max(88 * root.uiScale, root.avatarY - 96 * root.uiScale)
        color: Qt.rgba(0.075, 0.090, 0.120, 0.84)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.16)
        opacity: root.profileOpen ? 1 : 0
        scale: root.profileOpen ? 1 : 0.97

        Behavior on opacity {
            NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
        }

        Behavior on scale {
            NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
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
            text: "Profile picture"
            color: Qt.rgba(1, 1, 1, 0.96)
            font.pixelSize: 18 * root.uiScale
            font.weight: Font.DemiBold
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.topMargin: 52 * root.uiScale
            text: root.lockState.avatarCandidates.length > 0
                ? "Choose a local image for Maho Lock"
                : "Add images to ~/Pictures/Avatars or ~/Pictures/Profile"
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
                    width: 82 * root.uiScale
                    height: width
                    property string path: String(root.lockState.avatarCandidates[index] || "")

                    Rectangle {
                        anchors.fill: parent
                        radius: 18 * root.uiScale
                        color: Qt.rgba(1, 1, 1, candidatePointer.containsMouse ? 0.13 : 0.075)
                        border.width: 1
                        border.color: candidatePointer.containsMouse
                            ? Qt.rgba(1, 1, 1, 0.27)
                            : Qt.rgba(1, 1, 1, 0.10)

                        Behavior on color { ColorAnimation { duration: 120 } }
                        Behavior on border.color { ColorAnimation { duration: 120 } }
                    }

                    Image {
                        anchors.fill: parent
                        anchors.margins: 4 * root.uiScale
                        source: parent.path.length > 0 ? encodeURI("file://" + parent.path) : ""
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
            spacing: 10 * root.uiScale

            Rectangle {
                width: 118 * root.uiScale
                height: 38 * root.uiScale
                radius: height / 2
                color: initialsPointer.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.15)
                    : Qt.rgba(1, 1, 1, 0.095)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.13)

                Text {
                    anchors.centerIn: parent
                    text: "Use initials"
                    color: Qt.rgba(1, 1, 1, 0.91)
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
                width: 100 * root.uiScale
                height: 38 * root.uiScale
                radius: height / 2
                color: refreshPointer.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.15)
                    : Qt.rgba(1, 1, 1, 0.095)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.13)

                Text {
                    anchors.centerIn: parent
                    text: "Refresh"
                    color: Qt.rgba(1, 1, 1, 0.91)
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

        Text {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 24 * root.uiScale
            anchors.bottomMargin: 31 * root.uiScale
            text: "Preview only"
            color: Qt.rgba(1, 1, 1, 0.42)
            font.pixelSize: 11 * root.uiScale
        }
    }
}
