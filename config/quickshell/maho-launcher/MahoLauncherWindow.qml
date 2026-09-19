import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets
import "PointerSelectionPolicy.js" as PointerSelectionPolicy

PanelWindow {
    id: root

    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    focusable: true
    WlrLayershell.namespace: "maho-launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
    mask: Region { item: root.shown ? motionLayer : null }

    readonly property int surfaceWidth: 760
    readonly property int surfaceHeight: 790

    LauncherTheme { id: theme }
    LauncherBackend {
        id: backend
        query: searchInput.text
        onCloseRequested: root.closeLauncher()
        onModelChanged: Qt.callLater(function() {
            root.resetResultsToTop()
        })
    }

    property bool shown: false
    property bool closing: false
    property bool modeChanging: false
    property bool quickActionsOpen: false
    property int pendingMode: 0
    property int previousMode: 0
    property bool pointerSelectionEnabled: false
    property bool pointerAnchorValid: false
    property real pointerAnchorX: 0
    property real pointerAnchorY: 0
    property bool userPositioned: false
    readonly property real surfaceMargin: 20
    readonly property real pointerMovementThreshold: 4

    function centeredSurfaceX() {
        return Math.round((root.width - motionLayer.width) / 2)
    }

    function centeredSurfaceY() {
        return Math.round((root.height - motionLayer.height) / 2)
    }

    function centerSurface() {
        userPositioned = false
        motionLayer.x = centeredSurfaceX()
        motionLayer.y = centeredSurfaceY()
    }

    function clampSurface() {
        motionLayer.x = Math.max(surfaceMargin,
            Math.min(root.width - motionLayer.width - surfaceMargin, motionLayer.x))
        motionLayer.y = Math.max(surfaceMargin,
            Math.min(root.height - motionLayer.height - surfaceMargin, motionLayer.y))
    }

    onWidthChanged: Qt.callLater(function() {
        if (root.userPositioned)
            root.clampSurface()
        else
            root.centerSurface()
    })
    onHeightChanged: Qt.callLater(function() {
        if (root.userPositioned)
            root.clampSurface()
        else
            root.centerSurface()
    })

    readonly property real resultMaxY: Math.max(0, resultList.contentHeight - resultList.height)
    readonly property bool resultsScrollable: resultMaxY > 6
    readonly property bool resultsAtBottom: resultsScrollable && resultList.contentY >= resultMaxY - 10

    function resetPointerAuthority() {
        pointerSelectionEnabled = false
        if (pointerTracker.hovered) {
            pointerAnchorX = pointerTracker.point.position.x
            pointerAnchorY = pointerTracker.point.position.y
            pointerAnchorValid = true
        } else {
            pointerAnchorValid = false
        }
    }

    function resetResultsToTop() {
        resultPageScroll.stop()
        resetPointerAuthority()
        resultList.currentIndex = PointerSelectionPolicy.topIndex(resultList.count)
        if (resultList.currentIndex >= 0)
            resultList.positionViewAtBeginning()
    }

    function observePointer(pointerX, pointerY) {
        if (!shown || closing)
            return
        if (!pointerAnchorValid) {
            pointerAnchorX = pointerX
            pointerAnchorY = pointerY
            pointerAnchorValid = true
            return
        }
        if (!pointerSelectionEnabled && PointerSelectionPolicy.movedEnough(
                pointerAnchorX, pointerAnchorY, pointerX, pointerY,
                pointerMovementThreshold))
            pointerSelectionEnabled = true
    }

    function acceptPointerHover(rowIndex) {
        resultList.currentIndex = PointerSelectionPolicy.hoverIndex(
            resultList.currentIndex, rowIndex, pointerSelectionEnabled)
    }

    function closeLauncher() {
        if (closing)
            return
        closing = true
        quickActionsOpen = false
        shown = false
        closeTimer.restart()
    }

    function focusSearch() {
        quickActionsOpen = false
        searchInput.forceActiveFocus()
    }

    function switchMode(index) {
        if (index < 0 || index > 2)
            return
        quickActionsOpen = false
        if (index === backend.mode && !modeChanging) {
            searchInput.forceActiveFocus()
            return
        }
        previousMode = backend.mode
        pendingMode = index
        modeChanging = true
        modeSwap.restart()
    }

    function scrollResultsTo(targetY) {
        if (!root.resultsScrollable)
            return
        const bounded = Math.max(0, Math.min(root.resultMaxY, targetY))
        resultPageScroll.stop()
        resultPageScroll.from = resultList.contentY
        resultPageScroll.to = bounded
        resultPageScroll.start()

        if (resultList.count > 0) {
            const visualCenter = bounded + resultList.height * 0.38
            const row = Math.max(0, Math.min(resultList.count - 1, Math.floor(visualCenter / 58)))
            resultList.currentIndex = row
        }
    }

    function pageResults() {
        if (!root.resultsScrollable)
            return
        if (root.resultsAtBottom) {
            root.scrollResultsTo(0)
            return
        }
        root.scrollResultsTo(resultList.contentY + resultList.height * 0.76)
    }

    function goAppsHome() {
        quickActionsOpen = false
        if (backend.mode !== 0) {
            searchInput.text = ""
            root.switchMode(0)
            return
        }
        if (searchInput.text.length > 0) {
            searchInput.text = ""
            Qt.callLater(function() { searchInput.forceActiveFocus() })
            return
        }
        if (resultList.contentY > 4) {
            root.scrollResultsTo(0)
            return
        }
        searchInput.forceActiveFocus()
    }

    function runQuickCommand(action) {
        const allowed = ["terminal", "files", "lock", "diagnostics"]
        if (allowed.indexOf(action) < 0)
            return
        quickActionsOpen = false
        Quickshell.execDetached(["python3", backend.backendPath, "command", action])
        root.closeLauncher()
    }

    function moveSelection(delta) {
        quickActionsOpen = false
        if (resultList.count <= 0)
            return
        resetPointerAuthority()
        const current = Math.max(0, resultList.currentIndex)
        const next = Math.max(0, Math.min(resultList.count - 1, current + delta))
        resultList.currentIndex = next
        resultList.positionViewAtIndex(next, ListView.Contain)
    }

    function activateItem(index) {
        quickActionsOpen = false
        const authoritativeRow = backend.itemAt(index)
        if (!authoritativeRow)
            return
        resultList.currentIndex = PointerSelectionPolicy.clickIndex(index)
        backend.activate(authoritativeRow)
    }

    function activateSelected() {
        activateItem(resultList.currentIndex)
    }

    NumberAnimation {
        id: resultPageScroll
        target: resultList
        property: "contentY"
        duration: 310
        easing.type: Easing.OutCubic
    }

    Timer {
        id: closeTimer
        interval: 85
        onTriggered: Qt.quit()
    }

    Timer {
        id: modeSwap
        interval: 96
        onTriggered: {
            backend.mode = root.pendingMode
            searchInput.text = ""
            root.resetResultsToTop()
            root.modeChanging = false
            Qt.callLater(function() { searchInput.forceActiveFocus() })
        }
    }

    Component.onCompleted: {
        root.pendingMode = backend.mode
        Qt.callLater(function() {
            root.centerSurface()
            root.resetResultsToTop()
            root.shown = true
            searchInput.forceActiveFocus()
        })
    }

    Item {
        id: motionLayer
        width: Math.min(root.surfaceWidth, root.width - 40)
        height: Math.min(root.surfaceHeight, root.height - 40)
        x: 0
        y: 0
        opacity: root.shown ? 1 : 0

        onWidthChanged: Qt.callLater(function() {
            if (root.userPositioned)
                root.clampSurface()
            else
                root.centerSurface()
        })
        onHeightChanged: Qt.callLater(function() {
            if (root.userPositioned)
                root.clampSurface()
            else
                root.centerSurface()
        })

        HoverHandler {
            id: pointerTracker
            onPointChanged: root.observePointer(point.position.x, point.position.y)
        }
        // Opening gets a tiny lift/scale. Closing never reverses the geometry;
        // it simply fades away, which reads much faster and avoids ghost motion.
        scale: root.shown ? 1 : (root.closing ? 1 : 0.992)

        transform: Translate {
            y: root.shown ? 0 : (root.closing ? 0 : -4)
            Behavior on y {
                NumberAnimation {
                    duration: root.closing ? 0 : 145
                    easing.type: Easing.OutCubic
                }
            }
        }

        Behavior on opacity {
            NumberAnimation {
                duration: root.shown ? 145 : 68
                easing.type: Easing.OutCubic
            }
        }
        Behavior on scale {
            NumberAnimation {
                duration: root.closing ? 0 : 145
                easing.type: Easing.OutCubic
            }
        }

        Rectangle {
            anchors.fill: materialPanel
            anchors.margins: -4
            radius: 31
            antialiasing: true
            color: theme.outerGlow
            opacity: root.shown ? 1 : 0
            Behavior on opacity {
                NumberAnimation { duration: root.shown ? 145 : 65; easing.type: Easing.OutCubic }
            }
        }

        Rectangle {
            id: materialPanel
            anchors.fill: parent
            radius: 27
            antialiasing: true
            color: theme.shellFill
            border.width: 1
            border.color: theme.shellRim
            clip: true

            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                antialiasing: true
                color: "transparent"
                gradient: Gradient {
                    GradientStop { position: 0.00; color: theme.shellTopSpecular }
                    GradientStop { position: 0.20; color: theme.shellAccentWash }
                    GradientStop { position: 0.74; color: "transparent" }
                    GradientStop { position: 1.00; color: theme.shellBottomShade }
                }
            }

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 28
                anchors.rightMargin: 28
                anchors.top: parent.top
                anchors.topMargin: 1
                height: 1
                radius: 1
                antialiasing: true
                color: theme.shellInnerLine
            }

            Rectangle {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.left: parent.left
                width: 1
                radius: 1
                anchors.topMargin: 34
                anchors.bottomMargin: 34
                color: theme.shellSideLine
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                onClicked: function(mouse) {
                    if (root.quickActionsOpen)
                        root.quickActionsOpen = false
                    mouse.accepted = true
                }
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
                    z: 4
                    Layout.fillWidth: true
                    Layout.preferredHeight: 40

                    MouseArea {
                        id: launcherDragArea
                        z: 4
                        anchors.fill: parent
                        anchors.leftMargin: 54
                        anchors.rightMargin: 54
                        enabled: root.shown && !root.closing
                        hoverEnabled: true
                        preventStealing: true
                        cursorShape: Qt.SizeAllCursor
                        drag.target: motionLayer
                        drag.axis: Drag.XAndYAxis
                        drag.threshold: 2
                        drag.minimumX: root.surfaceMargin
                        drag.maximumX: Math.max(root.surfaceMargin,
                            root.width - motionLayer.width - root.surfaceMargin)
                        drag.minimumY: root.surfaceMargin
                        drag.maximumY: Math.max(root.surfaceMargin,
                            root.height - motionLayer.height - root.surfaceMargin)
                        onPressed: root.userPositioned = true
                        onReleased: root.clampSurface()
                        onCanceled: root.clampSurface()
                    }

                    LauncherIconButton {
                        z: 5
                        anchors.left: parent.left
                        anchors.verticalCenter: parent.verticalCenter
                        theme: theme
                        symbol: "grid"
                        emphasized: backend.mode === 0 && searchInput.text.length === 0 && resultList.contentY <= 4
                        onActivated: root.goAppsHome()
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
                        z: 5
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        theme: theme
                        symbol: "controls"
                        emphasized: root.quickActionsOpen
                        onActivated: {
                            root.quickActionsOpen = !root.quickActionsOpen
                            if (!root.quickActionsOpen)
                                searchInput.forceActiveFocus()
                        }
                    }
                }

                Rectangle {
                    id: searchField
                    Layout.fillWidth: true
                    Layout.preferredHeight: 50
                    radius: 17
                    antialiasing: true
                    color: searchInput.activeFocus ? theme.searchFocusedFill : theme.searchFill
                    border.width: 1
                    border.color: searchInput.activeFocus ? theme.searchFocusRim : theme.searchRim

                    Behavior on color { ColorAnimation { duration: 185; easing.type: Easing.OutCubic } }
                    Behavior on border.color { ColorAnimation { duration: 185; easing.type: Easing.OutCubic } }

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 18
                        anchors.rightMargin: 18
                        height: 1
                        radius: 1
                        antialiasing: true
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
                                antialiasing: true
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
                                color: theme.alpha(theme.muted, 0.70)
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

                                onTextChanged: root.quickActionsOpen = false

                                Keys.onPressed: function(event) {
                                    if (event.key === Qt.Key_Escape) {
                                        if (root.quickActionsOpen)
                                            root.quickActionsOpen = false
                                        else
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
                    radius: 16
                    antialiasing: true
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
                        radius: 14
                        antialiasing: true
                        border.width: 1
                        border.color: theme.selectedSegmentRim
                        gradient: Gradient {
                            GradientStop { position: 0; color: theme.selectedSegmentTop }
                            GradientStop { position: 0.48; color: theme.selectedSegment }
                            GradientStop { position: 1; color: theme.selectedSegmentBottom }
                        }

                        Behavior on x {
                            NumberAnimation { duration: 245; easing.type: Easing.OutCubic }
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
                                        : theme.alpha(theme.muted, segmentHover.hovered ? 0.90 : 0.76)
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
                                    acceptedButtons: Qt.LeftButton
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
                    radius: 18
                    antialiasing: true
                    color: theme.resultsFill
                    border.width: 1
                    border.color: theme.resultsRim
                    clip: true

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 20
                        anchors.rightMargin: 20
                        anchors.topMargin: 1
                        height: 1
                        radius: 1
                        antialiasing: true
                        color: theme.resultsSpecular
                    }

                    Item {
                        id: resultMotion
                        anchors.fill: parent
                        opacity: root.modeChanging ? 0 : 1
                        transform: Translate {
                            x: root.modeChanging
                                ? (root.pendingMode > root.previousMode ? 10 : -10)
                                : 0
                            Behavior on x {
                                NumberAnimation { duration: 205; easing.type: Easing.OutCubic }
                            }
                        }

                        Behavior on opacity { NumberAnimation { duration: 135; easing.type: Easing.OutCubic } }

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
                            highlightMoveDuration: 225
                            highlightResizeDuration: 170
                            highlightMoveVelocity: -1

                            highlight: Item {
                                Rectangle {
                                    anchors.fill: parent
                                    anchors.leftMargin: 3
                                    anchors.rightMargin: 3
                                    anchors.topMargin: 2
                                    anchors.bottomMargin: 2
                                    radius: 14
                                    antialiasing: true
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
                                    anchors.leftMargin: 24
                                    anchors.rightMargin: 24
                                    anchors.top: parent.top
                                    anchors.topMargin: 4
                                    height: 1
                                    radius: 1
                                    color: theme.selectedRowSpecular
                                }
                            }

                            delegate: LauncherResultRow {
                                width: ListView.view.width
                                theme: theme
                                selected: ListView.isCurrentItem
                                onHovered: function(rowIndex) { root.acceptPointerHover(rowIndex) }
                                onActivated: function(rowIndex) {
                                    root.activateItem(rowIndex)
                                }
                            }
                        }

                        Column {
                            anchors.centerIn: parent
                            visible: resultList.count === 0
                            spacing: 5

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: backend.mode === 0 && backend.appIndexBusy
                                    ? "Loading applications..."
                                    : (backend.mode === 1 && backend.fileSearchBusy ? "Searching files..." : "Nothing found")
                                color: theme.alpha(theme.foreground, 0.82)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 12
                                font.weight: Font.Medium
                            }

                            Text {
                                anchors.horizontalCenter: parent.horizontalCenter
                                text: backend.mode === 0
                                    ? (backend.appIndexBusy ? "Reading installed desktop entries" : "Try a different application name")
                                    : (backend.mode === 1 ? "Search your home folder" : "No command matches this search")
                                color: theme.alpha(theme.muted, 0.64)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 10
                            }
                        }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 32

                    Rectangle {
                        id: footerControl
                        anchors.centerIn: parent
                        width: Math.max(116, footerLabel.implicitWidth + 42)
                        height: 28
                        radius: 14
                        antialiasing: true
                        color: footerHover.hovered && root.resultsScrollable ? theme.controlHover : "transparent"
                        border.width: footerHover.hovered && root.resultsScrollable ? 1 : 0
                        border.color: theme.controlRim
                        opacity: resultList.count > 0 ? 1 : 0
                        scale: footerTap.pressed ? 0.975 : (footerHover.hovered && root.resultsScrollable ? 1.012 : 1)

                        Behavior on width { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
                        Behavior on color { ColorAnimation { duration: 150; easing.type: Easing.OutCubic } }
                        Behavior on opacity { NumberAnimation { duration: 160 } }
                        Behavior on scale { NumberAnimation { duration: 145; easing.type: Easing.OutCubic } }

                        Row {
                            anchors.centerIn: parent
                            spacing: 8

                            Text {
                                id: footerLabel
                                text: {
                                    if (!root.resultsScrollable)
                                        return resultList.count + (backend.mode === 0 ? " apps" : (backend.mode === 1 ? " results" : " commands"))
                                    if (root.resultsAtBottom)
                                        return "Back to top"
                                    return backend.mode === 0 ? "Show more apps" : (backend.mode === 1 ? "Show more files" : "Show more commands")
                                }
                                color: theme.alpha(theme.muted, footerHover.hovered && root.resultsScrollable ? 0.92 : 0.74)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 10
                                font.weight: Font.Medium
                                renderType: Text.NativeRendering
                                Behavior on color { ColorAnimation { duration: 145 } }
                            }

                            Item {
                                width: root.resultsScrollable ? 12 : 0
                                height: 12
                                visible: root.resultsScrollable
                                rotation: root.resultsAtBottom ? 180 : 0
                                opacity: footerHover.hovered ? 0.88 : 0.68

                                Behavior on width { NumberAnimation { duration: 160 } }
                                Behavior on rotation { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
                                Behavior on opacity { NumberAnimation { duration: 140 } }

                                Rectangle {
                                    width: 6
                                    height: 1.4
                                    radius: 0.7
                                    x: 1
                                    y: 5
                                    rotation: 42
                                    color: theme.muted
                                    antialiasing: true
                                }
                                Rectangle {
                                    width: 6
                                    height: 1.4
                                    radius: 0.7
                                    x: 5
                                    y: 5
                                    rotation: -42
                                    color: theme.muted
                                    antialiasing: true
                                }
                            }
                        }

                        HoverHandler {
                            id: footerHover
                            cursorShape: root.resultsScrollable ? Qt.PointingHandCursor : Qt.ArrowCursor
                        }
                        TapHandler {
                            id: footerTap
                            enabled: root.resultsScrollable
                            acceptedButtons: Qt.LeftButton
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: root.pageResults()
                        }
                    }
                }
            }

            Rectangle {
                id: quickActions
                z: 30
                anchors.top: parent.top
                anchors.right: parent.right
                anchors.topMargin: 64
                anchors.rightMargin: 20
                width: 232
                height: 190
                radius: 19
                antialiasing: true
                color: theme.alpha(theme.insetColor, 0.90)
                border.width: 1
                border.color: theme.alpha(theme.foreground, 0.075)
                opacity: root.quickActionsOpen ? 1 : 0
                visible: opacity > 0.001
                scale: root.quickActionsOpen ? 1 : 0.97
                clip: true

                transform: Translate {
                    y: root.quickActionsOpen ? 0 : -7
                    Behavior on y { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }
                }

                Behavior on opacity { NumberAnimation { duration: 165; easing.type: Easing.OutCubic } }
                Behavior on scale { NumberAnimation { duration: 190; easing.type: Easing.OutCubic } }

                Rectangle {
                    anchors.fill: parent
                    radius: parent.radius
                    antialiasing: true
                    color: "transparent"
                    gradient: Gradient {
                        GradientStop { position: 0; color: theme.alpha(theme.foreground, 0.035) }
                        GradientStop { position: 0.42; color: "transparent" }
                        GradientStop { position: 1; color: theme.alpha(theme.accent, 0.022) }
                    }
                }

                Column {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 2

                    Text {
                        text: "Quick actions"
                        color: theme.alpha(theme.muted, 0.70)
                        font.family: "Inter, Noto Sans, sans-serif"
                        font.pixelSize: 9
                        font.weight: Font.Medium
                        leftPadding: 8
                        height: 24
                        verticalAlignment: Text.AlignVCenter
                    }

                    Repeater {
                        model: [
                            { "id": "terminal", "name": "Terminal", "icon": "utilities-terminal" },
                            { "id": "files", "name": "Files", "icon": "system-file-manager" },
                            { "id": "lock", "name": "Lock Screen", "icon": "system-lock-screen" },
                            { "id": "diagnostics", "name": "Diagnostics", "icon": "utilities-system-monitor" }
                        ]

                        Rectangle {
                            required property var modelData
                            width: 212
                            height: 36
                            radius: 11
                            antialiasing: true
                            color: quickHover.hovered ? theme.controlHover : "transparent"
                            scale: quickTap.pressed ? 0.985 : 1

                            Behavior on color { ColorAnimation { duration: 140; easing.type: Easing.OutCubic } }
                            Behavior on scale { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }

                            IconImage {
                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.verticalCenter: parent.verticalCenter
                                width: 18
                                height: 18
                                source: Quickshell.iconPath(parent.modelData.icon, "")
                                asynchronous: true
                                mipmap: true
                                opacity: quickHover.hovered ? 0.96 : 0.76
                                Behavior on opacity { NumberAnimation { duration: 130 } }
                            }

                            Text {
                                anchors.left: parent.left
                                anchors.leftMargin: 40
                                anchors.verticalCenter: parent.verticalCenter
                                text: parent.modelData.name
                                color: theme.textPrimary
                                opacity: quickHover.hovered ? 1 : 0.88
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 11
                                font.weight: Font.Medium
                                renderType: Text.NativeRendering
                                Behavior on opacity { NumberAnimation { duration: 130 } }
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.rightMargin: 11
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.verticalCenterOffset: -1
                                text: "›"
                                color: theme.alpha(theme.muted, quickHover.hovered ? 0.74 : 0.46)
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 16
                                renderType: Text.NativeRendering
                                Behavior on color { ColorAnimation { duration: 130 } }
                            }

                            HoverHandler {
                                id: quickHover
                                cursorShape: Qt.PointingHandCursor
                            }
                            TapHandler {
                                id: quickTap
                                acceptedButtons: Qt.LeftButton
                                gesturePolicy: TapHandler.ReleaseWithinBounds
                                onTapped: root.runQuickCommand(parent.modelData.id)
                            }
                        }
                    }
                }
            }
        }
    }
}
