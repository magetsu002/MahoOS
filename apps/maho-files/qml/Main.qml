import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root

    width: 1180
    height: 760
    minimumWidth: 820
    minimumHeight: 560
    visible: true
    title: "Maho Files"
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    property color baseBackground: mahoPalette.background
    property color surface: mahoPalette.surface
    property color surfaceElevated: mahoPalette.surfaceElevated
    property color foreground: mahoPalette.foreground
    property color muted: mahoPalette.muted
    property color accent: mahoPalette.accent
    property color borderColor: mahoPalette.border
    property bool lightMode: mahoPalette.mode === "light"

    function alpha(color, amount) {
        return Qt.rgba(color.r, color.g, color.b, amount)
    }

    function mix(first, second, amount) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            first.r * (1 - t) + second.r * t,
            first.g * (1 - t) + second.g * t,
            first.b * (1 - t) + second.b * t,
            first.a * (1 - t) + second.a * t
        )
    }

    readonly property color familyShell: mix(surfaceElevated, baseBackground, lightMode ? 0.28 : 0.48)
    readonly property color shellFill: alpha(familyShell, lightMode ? 0.72 : 0.60)
    readonly property color sidebarFill: alpha(mix(surfaceElevated, baseBackground, 0.55), lightMode ? 0.48 : 0.42)
    readonly property color toolbarFill: alpha(mix(surfaceElevated, baseBackground, 0.44), lightMode ? 0.38 : 0.30)
    readonly property color contentFill: alpha(mix(surface, baseBackground, 0.62), lightMode ? 0.26 : 0.18)
    readonly property color hoverFill: alpha(foreground, lightMode ? 0.075 : 0.055)
    readonly property color selectedFill: alpha(mix(surfaceElevated, accent, 0.22), lightMode ? 0.54 : 0.48)
    readonly property color selectedRim: alpha(accent, 0.20)
    readonly property color quietRim: alpha(foreground, lightMode ? 0.13 : 0.095)
    readonly property color divider: alpha(foreground, lightMode ? 0.10 : 0.065)

    Shortcut {
        sequence: "Alt+Left"
        onActivated: directoryModel.goBack()
    }
    Shortcut {
        sequence: "Alt+Right"
        onActivated: directoryModel.goForward()
    }
    Shortcut {
        sequence: "Alt+Up"
        onActivated: directoryModel.goUp()
    }
    Shortcut {
        sequence: "Ctrl+H"
        onActivated: directoryModel.showHidden = !directoryModel.showHidden
    }
    Shortcut {
        sequence: "F5"
        onActivated: directoryModel.reload()
    }

    component NavigationButton: Rectangle {
        id: navigationButton
        required property string glyph
        property bool enabledState: true
        signal triggered()

        width: 38
        height: 38
        radius: 14
        color: pointer.hovered && enabledState ? root.hoverFill : "transparent"
        border.width: pointer.hovered && enabledState ? 1 : 0
        border.color: root.alpha(root.foreground, 0.08)
        opacity: enabledState ? 1 : 0.34

        Behavior on color { ColorAnimation { duration: 150 } }

        Text {
            anchors.centerIn: parent
            text: navigationButton.glyph
            color: root.foreground
            font.pixelSize: 24
            font.weight: Font.Medium
        }

        HoverHandler { id: pointer }
        TapHandler {
            enabled: navigationButton.enabledState
            onTapped: navigationButton.triggered()
        }
    }

    Rectangle {
        id: shell
        anchors.fill: parent
        anchors.margins: 1
        radius: 28
        color: root.shellFill
        border.width: 1
        border.color: root.quietRim
        clip: true

        Rectangle {
            anchors.fill: parent
            radius: shell.radius
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.00; color: root.alpha(root.foreground, root.lightMode ? 0.13 : 0.105) }
                GradientStop { position: 0.055; color: root.alpha(root.foreground, root.lightMode ? 0.035 : 0.026) }
                GradientStop { position: 0.18; color: "transparent" }
                GradientStop { position: 1.00; color: root.alpha(root.baseBackground, root.lightMode ? 0.015 : 0.045) }
            }
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            Rectangle {
                id: toolbar
                Layout.fillWidth: true
                Layout.preferredHeight: 74
                color: root.toolbarFill

                DragHandler {
                    target: null
                    acceptedButtons: Qt.LeftButton
                    onActiveChanged: {
                        if (active)
                            root.startSystemMove()
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: root.divider
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 18
                    anchors.rightMargin: 16
                    spacing: 7

                    NavigationButton {
                        glyph: "‹"
                        enabledState: directoryModel.canGoBack
                        onTriggered: directoryModel.goBack()
                    }
                    NavigationButton {
                        glyph: "›"
                        enabledState: directoryModel.canGoForward
                        onTriggered: directoryModel.goForward()
                    }
                    NavigationButton {
                        glyph: "⌃"
                        onTriggered: directoryModel.goUp()
                    }
                    NavigationButton {
                        glyph: "⌂"
                        onTriggered: directoryModel.goHome()
                    }

                    Rectangle {
                        Layout.leftMargin: 8
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        radius: 16
                        color: root.alpha(root.mix(root.surfaceElevated, root.baseBackground, 0.58), root.lightMode ? 0.48 : 0.40)
                        border.width: 1
                        border.color: pathField.activeFocus
                            ? root.alpha(root.accent, 0.28)
                            : root.alpha(root.foreground, 0.07)

                        TextField {
                            id: pathField
                            anchors.fill: parent
                            anchors.leftMargin: 14
                            anchors.rightMargin: 14
                            text: directoryModel.displayPath
                            color: root.foreground
                            placeholderText: "Location"
                            placeholderTextColor: root.alpha(root.muted, 0.65)
                            font.pixelSize: 14
                            selectByMouse: true
                            background: Item {}

                            onActiveFocusChanged: {
                                if (activeFocus)
                                    selectAll()
                            }
                            onAccepted: {
                                directoryModel.openLocation(text)
                                focus = false
                            }

                            Connections {
                                target: directoryModel
                                function onCurrentUrlChanged() {
                                    if (!pathField.activeFocus)
                                        pathField.text = directoryModel.displayPath
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: hiddenToggle
                        width: 38
                        height: 38
                        radius: 14
                        color: directoryModel.showHidden
                            ? root.alpha(root.accent, 0.12)
                            : hiddenHover.hovered ? root.hoverFill : "transparent"
                        border.width: directoryModel.showHidden ? 1 : 0
                        border.color: root.alpha(root.accent, 0.18)

                        Text {
                            anchors.centerIn: parent
                            text: "· · ·"
                            color: directoryModel.showHidden ? root.accent : root.foreground
                            font.pixelSize: 14
                            font.bold: true
                        }

                        HoverHandler { id: hiddenHover }
                        TapHandler { onTapped: directoryModel.showHidden = !directoryModel.showHidden }
                    }

                    Rectangle {
                        id: closeButton
                        width: 42
                        height: 42
                        radius: 21
                        color: closeHover.hovered
                            ? root.alpha(root.mix(root.accent, root.foreground, 0.24), root.lightMode ? 0.22 : 0.18)
                            : root.alpha(root.foreground, root.lightMode ? 0.045 : 0.035)
                        border.width: 1
                        border.color: closeHover.hovered
                            ? root.alpha(root.mix(root.accent, root.foreground, 0.38), 0.46)
                            : root.alpha(root.foreground, 0.12)
                        scale: closePress.pressed ? 0.94 : 1

                        Behavior on color { ColorAnimation { duration: 150 } }
                        Behavior on border.color { ColorAnimation { duration: 150 } }
                        Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

                        Item {
                            anchors.centerIn: parent
                            width: 14
                            height: 14

                            Rectangle {
                                anchors.centerIn: parent
                                width: 15
                                height: 1.6
                                radius: 0.8
                                rotation: 45
                                color: root.foreground
                                antialiasing: true
                            }
                            Rectangle {
                                anchors.centerIn: parent
                                width: 15
                                height: 1.6
                                radius: 0.8
                                rotation: -45
                                color: root.foreground
                                antialiasing: true
                            }
                        }

                        HoverHandler { id: closeHover }
                        TapHandler {
                            id: closePress
                            onTapped: root.close()
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Rectangle {
                    Layout.preferredWidth: 236
                    Layout.fillHeight: true
                    color: root.sidebarFill

                    Rectangle {
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.right: parent.right
                        width: 1
                        color: root.divider
                    }

                    ListView {
                        id: placesView
                        anchors.fill: parent
                        anchors.margins: 12
                        clip: true
                        model: placesModel
                        spacing: 2
                        section.property: "group"
                        section.criteria: ViewSection.FullString

                        section.delegate: Item {
                            width: placesView.width
                            height: 38

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 8
                                anchors.bottom: parent.bottom
                                anchors.bottomMargin: 6
                                text: section.toUpperCase()
                                color: root.alpha(root.muted, 0.65)
                                font.pixelSize: 10
                                font.weight: Font.DemiBold
                                font.letterSpacing: 0.9
                            }
                        }

                        delegate: Item {
                            id: placeDelegate
                            required property int index
                            required property string display
                            required property url url
                            required property string iconName
                            required property bool isHidden

                            width: placesView.width
                            height: isHidden ? 0 : 38
                            visible: !isHidden

                            property bool exactCurrent: String(url) === String(directoryModel.currentUrl)

                            Rectangle {
                                anchors.fill: parent
                                radius: 12
                                color: placeDelegate.exactCurrent
                                    ? root.selectedFill
                                    : placeHover.hovered ? root.hoverFill : "transparent"
                                border.width: placeDelegate.exactCurrent ? 1 : 0
                                border.color: root.selectedRim
                                Behavior on color { ColorAnimation { duration: 145 } }
                            }

                            Row {
                                anchors.fill: parent
                                anchors.leftMargin: 10
                                anchors.rightMargin: 8
                                spacing: 10

                                Image {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 19
                                    height: 19
                                    sourceSize: Qt.size(38, 38)
                                    source: "image://mahoicons/" + encodeURIComponent(placeDelegate.iconName)
                                    smooth: true
                                    mipmap: true
                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 42
                                    text: placeDelegate.display
                                    color: root.foreground
                                    font.pixelSize: 13
                                    elide: Text.ElideRight
                                }
                            }

                            HoverHandler { id: placeHover }
                            TapHandler { onTapped: directoryModel.openUrl(placeDelegate.url) }
                        }
                    }
                }

                Rectangle {
                    id: contentArea
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: root.contentFill

                    GridView {
                        id: grid
                        anchors.fill: parent
                        anchors.margins: 18
                        cellWidth: 132
                        cellHeight: 118
                        clip: true
                        model: directoryModel
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: true
                        focus: true

                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }

                        delegate: Item {
                            id: fileDelegate
                            required property int index
                            required property string name
                            required property url url
                            required property string iconName
                            required property bool isDirectory
                            required property string mimeComment

                            width: grid.cellWidth
                            height: grid.cellHeight

                            property bool selected: GridView.isCurrentItem

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 3
                                radius: 18
                                color: fileDelegate.selected
                                    ? root.selectedFill
                                    : fileHover.hovered ? root.hoverFill : "transparent"
                                border.width: fileDelegate.selected ? 1 : 0
                                border.color: root.selectedRim
                                Behavior on color { ColorAnimation { duration: 150 } }
                            }

                            Column {
                                anchors.fill: parent
                                anchors.topMargin: 12
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 8

                                Image {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: 58
                                    height: 58
                                    sourceSize: Qt.size(116, 116)
                                    source: "image://mahoicons/" + encodeURIComponent(fileDelegate.iconName)
                                    fillMode: Image.PreserveAspectFit
                                    smooth: true
                                    mipmap: true
                                }

                                Text {
                                    width: parent.width
                                    text: fileDelegate.name
                                    color: root.foreground
                                    horizontalAlignment: Text.AlignHCenter
                                    font.pixelSize: 12
                                    maximumLineCount: 2
                                    wrapMode: Text.Wrap
                                    elide: Text.ElideRight
                                }
                            }

                            HoverHandler { id: fileHover }
                            TapHandler {
                                acceptedButtons: Qt.LeftButton
                                onTapped: grid.currentIndex = fileDelegate.index
                                onDoubleTapped: directoryModel.openIndex(fileDelegate.index)
                            }
                        }

                        Keys.onReturnPressed: {
                            if (currentIndex >= 0)
                                directoryModel.openIndex(currentIndex)
                        }
                        Keys.onEnterPressed: {
                            if (currentIndex >= 0)
                                directoryModel.openIndex(currentIndex)
                        }
                    }

                    BusyIndicator {
                        anchors.centerIn: parent
                        running: directoryModel.loading && grid.count === 0
                        visible: running
                    }

                    Column {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 80, 440)
                        spacing: 10
                        visible: directoryModel.errorString.length > 0

                        Text {
                            width: parent.width
                            text: "Couldn’t open this location"
                            color: root.foreground
                            font.pixelSize: 18
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: parent.width
                            text: directoryModel.errorString
                            color: root.alpha(root.muted, 0.78)
                            font.pixelSize: 13
                            wrapMode: Text.Wrap
                            horizontalAlignment: Text.AlignHCenter
                        }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                color: root.alpha(root.mix(root.surfaceElevated, root.baseBackground, 0.55), root.lightMode ? 0.32 : 0.26)

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 1
                    color: root.divider
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 22
                    anchors.rightMargin: 22

                    Text {
                        text: grid.count + (grid.count === 1 ? " item" : " items")
                        color: root.alpha(root.muted, 0.76)
                        font.pixelSize: 11
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        visible: directoryModel.showHidden
                        text: "Hidden files visible"
                        color: root.alpha(root.accent, 0.82)
                        font.pixelSize: 11
                    }

                    Text {
                        text: directoryModel.loading ? "Loading…" : "KIO"
                        color: root.alpha(root.muted, 0.60)
                        font.pixelSize: 11
                    }
                }
            }
        }
    }

    Item {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 14
        height: 14
        HoverHandler { cursorShape: Qt.SizeFDiagCursor }
        DragHandler {
            target: null
            onActiveChanged: {
                if (active)
                    root.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
            }
        }
    }
}
