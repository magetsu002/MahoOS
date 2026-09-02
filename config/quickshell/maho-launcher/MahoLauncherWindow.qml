import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland

PanelWindow {
    id: root

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    color: "transparent"
    exclusiveZone: 0
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    focusable: true
    WlrLayershell.namespace: "maho-launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    readonly property int surfaceWidth: 760
    readonly property int surfaceHeight: 790

    LauncherTheme { id: theme }
    LauncherBackend {
        id: backend
        query: searchInput.text
        onCloseRequested: root.closeLauncher()
        onModelChanged: Qt.callLater(function() {
            resultList.currentIndex = resultList.count > 0 ? 0 : -1
            if (resultList.currentIndex >= 0)
                resultList.positionViewAtBeginning()
        })
    }

    property bool shown: false
    property bool closing: false
    property bool modeChanging: false
    property int pendingMode: 0
    property int previousMode: 0

    function closeLauncher() {
        if (closing)
            return
        closing = true
        shown = false
        closeTimer.restart()
    }

    function focusSearch() {
        searchInput.forceActiveFocus()
    }

    function switchMode(index) {
        if (index < 0 || index > 2)
            return
        if (index === backend.mode && !modeChanging) {
            searchInput.forceActiveFocus()
            return
        }

        previousMode = backend.mode
        pendingMode = index
        modeChanging = true
        modeSwap.restart()
    }

    function moveSelection(delta) {
        if (resultList.count <= 0)
            return
        const current = Math.max(0, resultList.currentIndex)
        const next = Math.max(0, Math.min(resultList.count - 1, current + delta))
        resultList.currentIndex = next
        resultList.positionViewAtIndex(next, ListView.Contain)
    }

    function activateSelected() {
        if (resultList.currentIndex < 0 || !resultList.currentItem)
            return
        backend.activate(resultList.currentItem.modelData)
    }

    Timer {
        id: closeTimer
        interval: 190
        onTriggered: Qt.quit()
    }

    Timer {
        id: modeSwap
        interval: 92
        onTriggered: {
            backend.mode = root.pendingMode
            searchInput.text = ""
            resultList.currentIndex = resultList.count > 0 ? 0 : -1
            root.modeChanging = false
            Qt.callLater(function() { searchInput.forceActiveFocus() })
        }
    }

    Component.onCompleted: {
        root.pendingMode = backend.mode
        Qt.callLater(function() {
            root.shown = true
            searchInput.forceActiveFocus()
        })
    }

    // Maho Link/Bluetooth-style full-screen material plane. The compositor
    // blur now sees the entire backdrop instead of only the launcher rectangle,
    // which is what makes color and luminance feel reflected through the glass.
    Rectangle {
        id: backdropDim
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, root.shown ? 0.105 : 0)
        Behavior on color { ColorAnimation { duration: root.shown ? 220 : 165; easing.type: Easing.OutCubic } }
    }

    MouseArea {
        anchors.fill: parent
        enabled: root.shown && !root.closing
        onClicked: root.closeLauncher()
    }

    Item {
        id: motionLayer
        width: Math.min(root.surfaceWidth, root.width - 40)
        height: Math.min(root.surfaceHeight, root.height - 40)
        anchors.centerIn: parent
        opacity: root.shown ? 1 : 0
        scale: root.shown ? 1 : 0.978

        transform: Translate {
            id: openTranslate
            y: root.shown ? 0 : -11
            Behavior on y {
                NumberAnimation {
                    duration: root.shown ? 235 : 160
                    easing.type: Easing.OutCubic
                }
            }
        }

        Behavior on opacity {
            NumberAnimation { duration: root.shown ? 225 : 155; easing.type: Easing.OutCubic }
        }
        Behavior on scale {
            NumberAnimation { duration: root.shown ? 250 : 165; easing.type: Easing.OutCubic }
        }

        Rectangle {
            anchors.fill: materialPanel
            anchors.margins: -5
            radius: 30
            color: theme.outerGlow
            opacity: root.shown ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 230 } }
        }

        Rectangle {
            id: materialPanel
            anchors.fill: parent
            radius: 25
            color: theme.shellFill
            border.width: 1
            border.color: theme.shellRim
            clip: true

            // A very soft environment wash. Most perceived color should come
            // from the real blurred wallpaper behind this translucent surface.
            Rectangle {
                anchors.fill: parent
                color: "transparent"
                gradient: Gradient {
                    GradientStop { position: 0.00; color: theme.shellTopSpecular }
                    GradientStop { position: 0.22; color: theme.shellAccentWash }
                    GradientStop { position: 0.72; color: "transparent" }
                    GradientStop { position: 1.00; color: theme.shellBottomShade }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 22
                anchors.rightMargin: 22
                anchors.top: parent.top
                height: 1
                color: theme.shellInnerLine
            }

            Rectangle {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                width: 1
                anchors.topMargin: 24
                anchors.bottomMargin: 24
                color: theme.shellSideLine
            }

            // Consume blank clicks inside the material so only clicks outside
            // the launcher dismiss it.
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                onClicked: function(mouse) { mouse.accepted = true }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                anchors.topMargin: 18
                anchors.bottomMargin: 14
                spacing: 12

                Item {
                    id: header
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40

                    LauncherIconButton {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        theme: theme
                        symbol: "grid"
                        emphasized: backend.mode === 0
                        onActivated: {
                            searchInput.text = ""
                            root.switchMode(0)
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        text: "Maho Launcher"
                        color: theme.textPrimary
                        font.family: "Inter, Noto Sans, sans-serif"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                        renderType: Text.NativeRendering
                    }

                    LauncherIconButton {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        theme: theme
                        symbol: "controls"
                        emphasized: backend.mode === 2
                        onActivated: root.switchMode(2)
                    }
                }

                Rectangle {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.preferredHeight: 50
                    radius: 16
                    color: searchInput.activeFocus ? theme.searchFocusedFill : theme.searchFill
                    border.width: 1
                    border.color: searchInput.activeFocus ? theme.searchFocusRim : theme.searchRim

                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    Behavior on border.color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        height: 1
                        color: searchInput.activeFocus ? theme.searchSpecularFocus : theme.searchSpecular
                        Behavior on color { ColorAnimation { duration: 180 } }
                    }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 15
                        anchors.rightMargin: 15
                        spacing: 12

                        Item {
                            Layout.preferredWidth: 20
                            Layout.preferredHeight: 20
                            Layout.alignment: Qt.AlignVCenter
                            opacity: searchInput.activeFocus ? 0.96 : 0.68
                            scale: searchInput.activeFocus ? 1.03 : 1

                            Rectangle {
                                x: 1
                                y: 1
                                width: 13
                                height: 13
                                radius: 7
                                color: "transparent"
                                border.width: 2
                                border.color: theme.searchGlyph
                            }
                            Rectangle {
                                x: 13
                                y: 13
                                width: 7
                                height: 2
                                radius: 1
                                rotation: 45
                                transformOrigin: Item.Left
                                color: theme.searchGlyph
                            }

                            Behavior on opacity { NumberAnimation { duration: 150 } }
                            Behavior on scale { NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: searchInput.text.length === 0
                                text: "Search apps, files, and commands..."
                                color: theme.alpha(theme.muted, 0.66)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 12
                                renderType: Text.NativeRendering
                            }

                            TextInput {
                                id: searchInput
                                anchors.fill: parent
                                verticalAlignment: TextInput.AlignVCenter
                                color: theme.textPrimary
                                selectionColor: theme.alpha(theme.accent, 0.34)
                                selectedTextColor: theme.textPrimary
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 12
                                renderType: Text.NativeRendering
                                clip: true
                                focus: true
                                activeFocusOnTab: true

                                Keys.onPressed: function(event) {
                                    if (event.key === Qt.Key_Escape) {
                                        root.closeLauncher()
                                        event.accepted = true
                                    } else if (event.key === Qt.Key_Up) {
                                        root.moveSelection(-1)
                                        event.accepted = true
                                    } else if (event.key === Qt.Key_Down) {
                                        root.moveSelection(1)
                                        event.accepted = true
                                    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                        root.activateSelected()
                                        event.accepted = true
                                    } else if (event.key === Qt.Key_Tab && !(event.modifiers & Qt.ShiftModifier)) {
                                        root.switchMode((backend.mode + 1) % 3)
                                        event.accepted = true
                                    } else if (event.key === Qt.Key_Backtab || (event.key === Qt.Key_Tab && (event.modifiers & Qt.ShiftModifier))) {
                                        root.switchMode((backend.mode + 2) % 3)
                                        event.accepted = true
                                    }
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    id: modeShelf
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    radius: 15
                    color: theme.segmentFill
                    border.width: 1
                    border.color: theme.segmentRim

                    property int visualMode: root.modeChanging ? root.pendingMode : backend.mode
                    property real segmentWidth: (width - 4) / 3

                    Rectangle {
                        id: selectedSegment
                        x: 2 + modeShelf.visualMode * modeShelf.segmentWidth
                        y: 2
                        width: modeShelf.segmentWidth
                        height: parent.height - 4
                        radius: 13
                        border.width: 1
                        border.color: theme.selectedSegmentRim
                        gradient: Gradient {
                            GradientStop { position: 0; color: theme.selectedSegmentTop }
                            GradientStop { position: 0.48; color: theme.selectedSegment }
                            GradientStop { position: 1; color: theme.selectedSegmentBottom }
                        }

                        Behavior on x {
                            NumberAnimation { duration: 230; easing.type: Easing.OutCubic }
                        }
                    }

                    Row {
                        anchors.fill: parent
                        anchors.margins: 2

                        Repeater {
                            model: ["Apps", "Files", "Commands"]

                            Item {
                                required property int index
                                required property string modelData
                                width: modeShelf.segmentWidth
                                height: modeShelf.height - 4
                                readonly property bool active: modeShelf.visualMode === index

                                Text {
                                    anchors.centerIn: parent
                                    anchors.verticalCenterOffset: segmentHover.hovered && !parent.active ? -1 : 0
                                    text: parent.modelData
                                    color: parent.active
                                        ? theme.textPrimary
                                        : theme.alpha(theme.muted, segmentHover.hovered ? 0.86 : 0.70)
                                    font.family: "Inter, Noto Sans, sans-serif"
                                    font.pixelSize: 11
                                    font.weight: parent.active ? Font.DemiBold : Font.Medium
                                    renderType: Text.NativeRendering

                                    Behavior on color { ColorAnimation { duration: 170 } }
                                    Behavior on anchors.verticalCenterOffset { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                                }

                                HoverHandler {
                                    id: segmentHover
                                    cursorShape: Qt.PointingHandCursor
                                }
                                TapHandler {
                                    gesturePolicy: TapHandler.ReleaseWithinBounds
                                    onTapped: root.switchMode(index)
                                }

                                scale: segmentHover.hovered ? 1.006 : 1
                                Behavior on scale { NumberAnimation { duration: 145; easing.type: Easing.OutCubic } }
                            }
                        }
                    }
                }

                Rectangle {
                    id: resultsViewport
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 522
                    radius: 16
                    color: theme.resultsFill
                    border.width: 1
                    border.color: theme.resultsRim
                    clip: true

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        height: 1
                        color: theme.resultsSpecular
                    }

                    Item {
                        id: resultMotion
                        anchors.fill: parent
                        opacity: root.modeChanging ? 0 : 1
                        transform: Translate {
                            id: modeTranslate
                            x: root.modeChanging
                                ? (root.pendingMode > root.previousMode ? 12 : -12)
                                : 0
                            Behavior on x {
                                NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
                            }
                        }

                        Behavior on opacity { NumberAnimation { duration: 125; easing.type: Easing.OutCubic } }

                        ListView {
                            id: resultList
                            anchors.fill: parent
                            anchors.topMargin: 2
                            anchors.bottomMargin: 2
                            clip: true
                            spacing: 0
                            model: backend.activeModel
                            currentIndex: count > 0 ? 0 : -1
                            boundsBehavior: Flickable.StopAtBounds
                            keyNavigationEnabled: false
                            highlightFollowsCurrentItem: true
                            highlightMoveDuration: 210
                            highlightResizeDuration: 160
                            highlightMoveVelocity: -1

                            highlight: Item {
                                Rectangle {
                                    anchors.fill: parent
                                    anchors.margins: 2
                                    radius: 14
                                    border.width: 1
                                    border.color: theme.selectedRowRim
                                    gradient: Gradient {
                                        GradientStop { position: 0; color: theme.selectedRowTop }
                                        GradientStop { position: 0.52; color: theme.selectedRow }
                                        GradientStop { position: 1; color: theme.selectedRowBottom }
                                    }
                                }
                                Rectangle {
                                    anchors.left: parent.left
                                    anchors.right: parent.right
                                    anchors.leftMargin: 18
                                    anchors.rightMargin: 18
                                    anchors.top: parent.top
                                    anchors.topMargin: 3
                                    height: 1
                                    color: theme.selectedRowSpecular
                                }
                            }

                            delegate: LauncherResultRow {
                                width: ListView.view.width
                                theme: theme
                                backend: backend
                                selected: ListView.isCurrentItem
                                onHovered: function(rowIndex) { resultList.currentIndex = rowIndex }
                                onActivated: function(rowIndex) {
                                    resultList.currentIndex = rowIndex
                                    backend.activate(modelData)
                                }
                            }
                        }

                        Column {
                            anchors.centerIn: parent
                            visible: resultList.count === 0
                            spacing: 5

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: backend.mode === 1 && backend.fileSearchBusy
                                    ? "Searching files..."
                                    : "Nothing found"
                                color: theme.alpha(theme.foreground, 0.78)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 12
                                font.weight: Font.Medium
                            }

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: backend.mode === 0
                                    ? "Try a different application name"
                                    : (backend.mode === 1 ? "Search your home folder" : "No command matches this search")
                                color: theme.alpha(theme.muted, 0.58)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 10
                            }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 26

                    Row {
                        anchors.centerIn: parent
                        spacing: 6
                        y: footerHover.hovered ? parent.height / 2 - height / 2 - 1 : parent.height / 2 - height / 2

                        Text {
                            text: backend.mode === 0 ? "Show more apps" : (backend.mode === 1 ? "More files" : "Commands")
                            color: theme.alpha(theme.muted, footerHover.hovered ? 0.82 : 0.64)
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 9
                            font.weight: Font.Medium
                            Behavior on color { ColorAnimation { duration: 140 } }
                        }

                        Text {
                            text: "⌄"
                            color: theme.alpha(theme.muted, footerHover.hovered ? 0.72 : 0.52)
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 11
                            Behavior on color { ColorAnimation { duration: 140 } }
                        }

                        Behavior on y { NumberAnimation { duration: 145; easing.type: Easing.OutCubic } }
                    }

                    HoverHandler {
                        id: footerHover
                        cursorShape: Qt.PointingHandCursor
                    }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: {
                            if (resultList.count <= 0)
                                return
                            const target = Math.min(resultList.count - 1, Math.max(0, resultList.currentIndex) + 7)
                            resultList.currentIndex = target
                            resultList.positionViewAtIndex(target, ListView.Contain)
                        }
                    }
                }
            }
        }
    }
}
