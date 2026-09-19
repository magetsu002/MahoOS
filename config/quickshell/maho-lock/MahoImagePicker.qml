import QtQuick

Item {
    id: root

    required property var lockState
    property bool open: false
    property string mode: "avatar"
    property real uiScale: 1
    property real progress: open ? 1 : 0
    signal closeRequested()
    signal imageSelected(string path)

    readonly property bool avatarMode: mode === "avatar"

    visible: open || progress > 0.001

    Behavior on progress {
        NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
    }

    onOpenChanged: {
        if (!open)
            return
        searchInput.text = ""
        root.lockState.openImageBrowser(root.mode)
    }

    function browse(path) {
        searchInput.text = ""
        root.lockState.browseImages(path, "", root.mode)
    }

    function choose(entry) {
        if (!entry)
            return
        const path = String(entry.path || "")
        if (path.length === 0)
            return
        if (entry.isDir === true) {
            root.browse(path)
            return
        }
        root.imageSelected(path)
    }

    Timer {
        id: searchDebounce
        interval: 110
        repeat: false
        onTriggered: root.lockState.browseImages(
            root.lockState.browserPath,
            searchInput.text,
            root.mode
        )
    }

    MouseArea {
        anchors.fill: parent
        z: 1
        enabled: root.visible
        onClicked: root.closeRequested()
    }

    Rectangle {
        id: panel
        z: 2
        anchors.centerIn: parent
        width: Math.min(root.width - 72 * root.uiScale, 930 * root.uiScale)
        height: Math.min(root.height - 92 * root.uiScale, 650 * root.uiScale)
        radius: 30 * root.uiScale
        antialiasing: true
        opacity: root.progress
        scale: 0.986 + root.progress * 0.014
        color: Qt.rgba(0.050, 0.064, 0.090, 0.955)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.16)
        clip: true

        transform: Translate {
            y: (1 - root.progress) * 7 * root.uiScale
        }

        MouseArea {
            anchors.fill: parent
            onClicked: function(mouse) { mouse.accepted = true }
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 28 * root.uiScale
            anchors.topMargin: 22 * root.uiScale
            text: root.avatarMode ? "Choose profile photo" : "Choose lock wallpaper"
            color: Qt.rgba(1, 1, 1, 0.97)
            font.pixelSize: 19 * root.uiScale
            font.weight: Font.DemiBold
        }

        Text {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 28 * root.uiScale
            anchors.topMargin: 51 * root.uiScale
            text: root.avatarMode
                ? "High-quality images from your files"
                : "Choose a dedicated lock-screen background"
            color: Qt.rgba(1, 1, 1, 0.60)
            font.pixelSize: 12 * root.uiScale
        }

        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 18 * root.uiScale
            anchors.topMargin: 18 * root.uiScale
            width: 36 * root.uiScale
            height: width
            radius: width / 2
            antialiasing: true
            color: closePointer.containsMouse
                ? Qt.rgba(1, 1, 1, 0.10)
                : "transparent"

            Text {
                anchors.fill: parent
                text: "×"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Qt.rgba(1, 1, 1, 0.84)
                font.pixelSize: 22 * root.uiScale
                font.weight: Font.Light
            }

            MouseArea {
                id: closePointer
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.closeRequested()
            }
        }

        Rectangle {
            id: pathBar
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: 24 * root.uiScale
            anchors.topMargin: 82 * root.uiScale
            width: parent.width - searchBar.width - 72 * root.uiScale
            height: 44 * root.uiScale
            radius: height / 2
            antialiasing: true
            color: Qt.rgba(1, 1, 1, 0.052)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.085)

            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 6 * root.uiScale
                width: 34 * root.uiScale
                height: width
                radius: width / 2
                antialiasing: true
                visible: root.lockState.browserParent.length > 0
                color: upPointer.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.10)
                    : "transparent"

                MahoIconV2 {
                    anchors.centerIn: parent
                    width: 16 * root.uiScale
                    height: 16 * root.uiScale
                    name: "arrow-left"
                    iconOpacity: 0.88
                }

                MouseArea {
                    id: upPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.browse(root.lockState.browserParent)
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
                    : "Loading default folder…"
                color: Qt.rgba(1, 1, 1, 0.70)
                font.pixelSize: 11 * root.uiScale
                elide: Text.ElideMiddle
            }
        }

        Rectangle {
            id: searchBar
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.rightMargin: 24 * root.uiScale
            anchors.topMargin: 82 * root.uiScale
            width: 250 * root.uiScale
            height: 44 * root.uiScale
            radius: height / 2
            antialiasing: true
            color: searchInput.activeFocus
                ? Qt.rgba(1, 1, 1, 0.082)
                : Qt.rgba(1, 1, 1, 0.052)
            border.width: 1
            border.color: searchInput.activeFocus
                ? Qt.rgba(1, 1, 1, 0.18)
                : Qt.rgba(1, 1, 1, 0.085)

            Behavior on color { ColorAnimation { duration: 120 } }
            Behavior on border.color { ColorAnimation { duration: 120 } }

            MahoIconV2 {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 13 * root.uiScale
                width: 16 * root.uiScale
                height: 16 * root.uiScale
                name: "search"
                iconOpacity: 0.68
            }

            TextInput {
                id: searchInput
                anchors.left: parent.left
                anchors.right: clearSearch.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 38 * root.uiScale
                anchors.rightMargin: 6 * root.uiScale
                color: Qt.rgba(1, 1, 1, 0.92)
                font.pixelSize: 12 * root.uiScale
                selectByMouse: true
                clip: true
                onTextChanged: searchDebounce.restart()
                Keys.onEscapePressed: {
                    text = ""
                    root.closeRequested()
                }
            }

            Text {
                anchors.left: searchInput.left
                anchors.verticalCenter: parent.verticalCenter
                visible: searchInput.text.length === 0
                text: "Search images"
                color: Qt.rgba(1, 1, 1, 0.42)
                font.pixelSize: 12 * root.uiScale
            }

            Rectangle {
                id: clearSearch
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 7 * root.uiScale
                width: 28 * root.uiScale
                height: width
                radius: width / 2
                visible: searchInput.text.length > 0
                color: clearPointer.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.10)
                    : "transparent"

                Text {
                    anchors.fill: parent
                    text: "×"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Qt.rgba(1, 1, 1, 0.68)
                    font.pixelSize: 16 * root.uiScale
                }

                MouseArea {
                    id: clearPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: searchInput.text = ""
                }
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
            anchors.topMargin: 18 * root.uiScale
            anchors.bottomMargin: 12 * root.uiScale
            clip: true
            model: root.lockState.browserEntries
            cellWidth: (root.avatarMode ? 148 : 206) * root.uiScale
            cellHeight: (root.avatarMode ? 148 : 132) * root.uiScale
            boundsBehavior: Flickable.StopAtBounds

            delegate: Item {
                required property int index
                property var entry: root.lockState.browserEntries[index] || ({})
                property bool isFolder: entry.isDir === true
                width: (root.avatarMode ? 136 : 194) * root.uiScale
                height: (root.avatarMode ? 136 : 120) * root.uiScale
                scale: entryPointer.pressed
                    ? 0.965
                    : (entryPointer.containsMouse ? 1.018 : 1)

                Behavior on scale {
                    NumberAnimation { duration: 115; easing.type: Easing.OutCubic }
                }

                Rectangle {
                    anchors.fill: parent
                    radius: 18 * root.uiScale
                    antialiasing: true
                    color: entryPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.105)
                        : Qt.rgba(1, 1, 1, 0.058)
                    border.width: 1
                    border.color: entryPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.18)
                        : Qt.rgba(1, 1, 1, 0.075)
                    clip: true

                    Image {
                        anchors.fill: parent
                        anchors.margins: 3 * root.uiScale
                        visible: !parent.parent.isFolder
                        source: !parent.parent.isFolder
                            ? encodeURI("file://" + String(parent.parent.entry.path || ""))
                            : ""
                        fillMode: Image.PreserveAspectCrop
                        smooth: true
                        mipmap: true
                        asynchronous: true
                        cache: true
                        sourceSize.width: root.avatarMode ? 768 : 1280
                        sourceSize.height: root.avatarMode ? 768 : 720
                    }

                    Item {
                        anchors.fill: parent
                        visible: parent.parent.isFolder

                        MahoIconV2 {
                            anchors.centerIn: parent
                            width: 42 * root.uiScale
                            height: 42 * root.uiScale
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
                            color: Qt.rgba(1, 1, 1, 0.90)
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
                    onClicked: root.choose(parent.entry)
                }
            }
        }

        Text {
            anchors.centerIn: browserGrid
            visible: root.lockState.browserPath.length > 0
                && root.lockState.browserEntries.length === 0
            text: searchInput.text.length > 0
                ? "No matching images below this folder"
                : "No image files in this folder"
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
                anchors.leftMargin: 28 * root.uiScale
                text: searchInput.text.length > 0
                    ? "Searching this folder and subfolders"
                    : "JPG · PNG · WEBP · AVIF · BMP"
                color: Qt.rgba(1, 1, 1, 0.44)
                font.pixelSize: 10.5 * root.uiScale
            }

            Rectangle {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 24 * root.uiScale
                width: (root.avatarMode ? 112 : 138) * root.uiScale
                height: 38 * root.uiScale
                radius: height / 2
                antialiasing: true
                color: footerPointer.pressed
                    ? Qt.rgba(1, 1, 1, 0.16)
                    : (footerPointer.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.12)
                        : Qt.rgba(1, 1, 1, 0.075))
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.11)

                Text {
                    anchors.fill: parent
                    text: root.avatarMode ? "Use initials" : "Shuffle"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
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
                        if (root.avatarMode)
                            root.lockState.clearAvatar()
                        else
                            root.lockState.shuffleLockWallpaper()
                        root.closeRequested()
                    }
                }
            }
        }
    }
}
