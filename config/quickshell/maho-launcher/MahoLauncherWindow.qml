import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets

PanelWindow {
    id: root

    color: "transparent"
    implicitWidth: 760
    implicitHeight: 730
    exclusiveZone: 0
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    focusable: true
    WlrLayershell.namespace: "maho-launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

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
        interval: 175
        onTriggered: Qt.quit()
    }

    Timer {
        id: modeSwap
        interval: 88
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

    Item {
        id: motionLayer
        anchors.fill: parent
        opacity: root.shown ? 1 : 0
        scale: root.shown ? 1 : 0.965
        transform: Translate {
            id: openTranslate
            y: root.shown ? 0 : -14
            Behavior on y {
                NumberAnimation {
                    duration: root.shown ? 225 : 145
                    easing.type: Easing.OutCubic
                }
            }
        }

        Behavior on opacity {
            NumberAnimation {
                duration: root.shown ? 215 : 145
                easing.type: Easing.OutCubic
            }
        }
        Behavior on scale {
            NumberAnimation {
                duration: root.shown ? 240 : 150
                easing.type: root.shown ? Easing.OutBack : Easing.InCubic
            }
        }

        Rectangle {
            anchors.fill: materialPanel
            anchors.margins: -3
            radius: 27
            color: theme.subtleGlow
            opacity: 0.72
        }

        Rectangle {
            id: materialPanel
            anchors.fill: parent
            anchors.margins: 1
            radius: 24
            color: theme.shellFill
            border.width: 1
            border.color: theme.shellRim
            clip: true

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 165
                gradient: Gradient {
                    GradientStop { position: 0; color: theme.shellTopGlow }
                    GradientStop { position: 1; color: "transparent" }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                anchors.top: parent.top
                height: 1
                color: theme.shellInnerLine
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
                    Layout.preferredHeight: 38

                    LauncherIconButton {
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        theme: theme
                        iconName: "view-app-grid-symbolic"
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
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        renderType: Text.NativeRendering
                    }

                    LauncherIconButton {
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        theme: theme
                        iconName: "preferences-system-symbolic"
                        hoverRotation: 10
                        emphasized: backend.mode === 2
                        onActivated: root.switchMode(2)
                    }
                }

                Rectangle {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.preferredHeight: 48
                    radius: 15
                    color: searchInput.activeFocus ? theme.searchFocusedFill : theme.searchFill
                    border.width: 1
                    border.color: searchInput.activeFocus ? theme.searchFocusRim : theme.searchRim

                    Behavior on color { ColorAnimation { duration: 170; easing.type: Easing.OutCubic } }
                    Behavior on border.color { ColorAnimation { duration: 170 } }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 15
                        anchors.rightMargin: 15
                        spacing: 12

                        IconImage {
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            Layout.alignment: Qt.AlignVCenter
                            source: Quickshell.iconPath("system-search-symbolic", "edit-find-symbolic")
                            opacity: searchInput.activeFocus ? 0.92 : 0.64
                            mipmap: true

                            Behavior on opacity { NumberAnimation { duration: 150 } }
                        }

                        Item {
                            Layout.fillWidth: true
                            Layout.fillHeight: true

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                visible: searchInput.text.length === 0
                                text: "Search apps, files, and commands..."
                                color: theme.alpha(theme.muted, 0.62)
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
                    Layout.preferredHeight: 42
                    radius: 14
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
                        radius: 12
                        border.width: 1
                        border.color: theme.selectedSegmentRim
                        gradient: Gradient {
                            GradientStop { position: 0; color: theme.selectedSegmentTop }
                            GradientStop { position: 1; color: theme.selectedSegment }
                        }

                        Behavior on x {
                            NumberAnimation { duration: 220; easing.type: Easing.OutCubic }
                        }
                    }

                    Row {
                        anchors.fill: parent
                        anchors.margins: 2

                        Repeater {
                            model: [
                                { "label": "Apps", "icon": "view-app-grid-symbolic" },
                                { "label": "Files", "icon": "folder-symbolic" },
                                { "label": "Commands", "icon": "system-run-symbolic" }
                            ]

                            Item {
                                required property int index
                                required property var modelData
                                width: modeShelf.segmentWidth
                                height: modeShelf.height - 4

                                readonly property bool active: modeShelf.visualMode === index

                                Row {
                                    anchors.centerIn: parent
                                    spacing: 8

                                    IconImage {
                                        anchors.verticalCenter: parent.verticalCenter
                                        width: 15
                                        height: 15
                                        source: Quickshell.iconPath(modelData.icon, true)
                                        opacity: active ? 0.94 : 0.54
                                        scale: active ? 1.02 : 0.96

                                        Behavior on opacity { NumberAnimation { duration: 170 } }
                                        Behavior on scale { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
                                    }

                                    Text {
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: modelData.label
                                        color: active ? theme.textPrimary : theme.alpha(theme.muted, 0.70)
                                        font.family: "Inter, Noto Sans, sans-serif"
                                        font.pixelSize: 11
                                        font.weight: active ? Font.DemiBold : Font.Medium
                                        renderType: Text.NativeRendering

                                        Behavior on color { ColorAnimation { duration: 170 } }
                                    }
                                }

                                HoverHandler { id: segmentHover }
                                TapHandler {
                                    gesturePolicy: TapHandler.ReleaseWithinBounds
                                    onTapped: root.switchMode(index)
                                }

                                scale: segmentHover.hovered ? 1.008 : 1
                                Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                            }
                        }
                    }
                }

                Rectangle {
                    id: resultsViewport
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 420
                    radius: 15
                    color: theme.resultsFill
                    border.width: 1
                    border.color: theme.resultsRim
                    clip: true

                    Item {
                        id: resultMotion
                        anchors.fill: parent
                        opacity: root.modeChanging ? 0 : 1
                        transform: Translate {
                            id: modeTranslate
                            x: root.modeChanging
                                ? (root.pendingMode > root.previousMode ? 10 : -10)
                                : 0
                            Behavior on x {
                                NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                            }
                        }

                        Behavior on opacity { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

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
                            highlightMoveDuration: 185
                            highlightResizeDuration: 140
                            highlightMoveVelocity: -1

                            highlight: Rectangle {
                                z: -1
                                radius: 13
                                border.width: 1
                                border.color: theme.selectedRowRim
                                gradient: Gradient {
                                    GradientStop { position: 0; color: theme.selectedRowTop }
                                    GradientStop { position: 1; color: theme.selectedRow }
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
                        spacing: 5

                        Text {
                            text: backend.mode === 0 ? "Show more apps" : (backend.mode === 1 ? "More files" : "Commands")
                            color: theme.alpha(theme.muted, 0.64)
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 9
                            font.weight: Font.Medium
                        }

                        Text {
                            text: "⌄"
                            color: theme.alpha(theme.muted, 0.52)
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 11
                        }
                    }

                    HoverHandler { id: footerHover }
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

                    opacity: footerHover.hovered ? 1 : 0.84
                    Behavior on opacity { NumberAnimation { duration: 140 } }
                }
            }
        }
    }
}
