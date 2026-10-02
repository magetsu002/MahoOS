import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: root

    width: 1180
    height: 760
    minimumWidth: 320
    minimumHeight: 240
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

    property string viewMode: "grid"
    property bool searchVisible: false
    readonly property bool contentScrollbarDragging:
        gridScrollBar.pressed || listScrollBar.pressed || placesScrollBar.pressed

    onViewModeChanged: Qt.callLater(function() {
        const view = root.viewMode === "grid" ? grid : listView
        view.contentY = root.boundedContentY(view, view.contentY)
        if (root.selectedIndex >= 0)
            view.positionViewAtIndex(root.selectedIndex, root.viewMode === "grid" ? GridView.Contain : ListView.Contain)
    })
    property int selectedIndex: -1
    property int selectionAnchor: -1
    property var selectedIndexes: []
    property bool selectionDragPending: false
    property bool selectionDragActive: false
    property bool selectionDragAdditive: false
    property var selectionDragBaseline: []
    property real selectionDragStartX: 0
    property real selectionDragStartY: 0
    property real selectionDragCurrentX: 0
    property real selectionDragCurrentY: 0
    property real sidebarWidth: 228
    property string folderDropTargetUrl: ""

    readonly property int selectedCount: selectedIndexes.length

    readonly property bool narrowWindow: width < 700
    readonly property bool compactToolbar: width < 760
    readonly property bool tinyToolbar: width < 560
    readonly property real effectiveSidebarWidth: narrowWindow
        ? 0
        : Math.min(sidebarWidth, Math.max(180, width * 0.34))

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

    function icon(name) {
        return "image://mahoicons/" + encodeURIComponent(name)
    }

    function dropAction(drop, destination) {
        const formats = drop.formats || []
        const internalDrag = formats.indexOf("application/x-maho-files-internal-drag") >= 0
        return directoryModel.preferredDropAction(
            drop.urls, destination, drop.supportedActions, internalDrag)
    }

    function acceptDrop(drop, destination) {
        const action = dropAction(drop, destination)
        if (!drop.hasUrls || action === Qt.IgnoreAction
                || !directoryModel.canDropUrlsTo(drop.urls, destination)) {
            drop.accepted = false
            return false
        }
        drop.accept(action)
        return true
    }

    function performDrop(drop, destination) {
        const action = dropAction(drop, destination)
        if (!drop.hasUrls || action === Qt.IgnoreAction
                || !directoryModel.canDropUrlsTo(drop.urls, destination)) {
            drop.accepted = false
            return false
        }
        directoryModel.dropUrls(drop.urls, destination, action)
        drop.accept(action)
        return true
    }

    function showSearch() {
        searchVisible = true
        Qt.callLater(function() {
            searchField.forceActiveFocus()
            searchField.selectAll()
        })
    }

    function closeSearch() {
        searchField.text = ""
        directoryModel.searchQuery = ""
        searchVisible = false
        Qt.callLater(function() {
            if (root.viewMode === "grid")
                grid.forceActiveFocus()
            else
                listView.forceActiveFocus()
        })
    }

    function textEntryHasFocus() {
        const active = root.activeFocusItem
        return active === searchField || active === pathField || active === nameField
    }

    function isSelected(index) {
        return selectedIndexes.indexOf(index) >= 0
    }

    function normalizedIndexes(indexes) {
        const unique = []
        for (let i = 0; i < indexes.length; ++i) {
            const row = Number(indexes[i])
            if (!isFinite(row) || row < 0 || unique.indexOf(row) >= 0)
                continue
            unique.push(row)
        }
        unique.sort(function(a, b) { return a - b })
        return unique
    }

    function applySelection(indexes, primaryIndex, preserveAnchor) {
        const next = normalizedIndexes(indexes)
        selectedIndexes = next
        selectedIndex = next.indexOf(primaryIndex) >= 0
            ? primaryIndex
            : (next.length > 0 ? next[next.length - 1] : -1)
        if (!preserveAnchor)
            selectionAnchor = selectedIndex
        directoryModel.setSelectedRows(next)
    }

    function clearSelection() {
        selectedIndexes = []
        selectedIndex = -1
        selectionAnchor = -1
        directoryModel.setSelectedRows([])
    }

    function selectSingle(index) {
        if (index < 0) {
            clearSelection()
            return
        }
        applySelection([index], index, false)
    }

    function selectClicked(index, modifiers) {
        if (index < 0)
            return

        const ctrl = (modifiers & Qt.ControlModifier) !== 0
        const shift = (modifiers & Qt.ShiftModifier) !== 0

        if (shift && selectionAnchor >= 0) {
            const first = Math.min(selectionAnchor, index)
            const last = Math.max(selectionAnchor, index)
            let range = []
            for (let row = first; row <= last; ++row)
                range.push(row)
            if (ctrl)
                range = selectedIndexes.concat(range)
            applySelection(range, index, true)
            return
        }

        if (ctrl) {
            const next = selectedIndexes.slice()
            const existing = next.indexOf(index)
            if (existing >= 0)
                next.splice(existing, 1)
            else
                next.push(index)
            applySelection(next, index, false)
            return
        }

        // Once a group is selected, pressing/clicking one member must not
        // destroy the group before it can be dragged. A click on an unselected
        // item or empty space still starts a new selection.
        if (selectedIndexes.length > 1 && isSelected(index)) {
            selectedIndex = index
            selectionAnchor = index
            directoryModel.setSelectedRows(selectedIndexes)
            return
        }

        selectSingle(index)
    }

    function selectAllVisibleModelRows() {
        const count = viewMode === "grid" ? grid.count : listView.count
        const rows = []
        for (let row = 0; row < count; ++row)
            rows.push(row)
        applySelection(rows, rows.length > 0 ? rows[rows.length - 1] : -1, false)
    }

    function selectionViewAt(contentX, contentY) {
        const view = viewMode === "grid" ? grid : listView
        if (!view || !view.visible)
            return null
        const point = contentArea.mapToItem(view, contentX, contentY)
        if (point.x < 0 || point.y < 0 || point.x >= view.width || point.y >= view.height)
            return null
        return view
    }

    function rowAtContentPoint(view, contentX, contentY) {
        const point = contentArea.mapToItem(view, contentX, contentY)
        return view.indexAt(point.x + view.contentX, point.y + view.contentY)
    }

    function clampContentPointToView(view, contentX, contentY) {
        const topLeft = view.mapToItem(contentArea, 0, 0)
        const bottomRight = view.mapToItem(contentArea, view.width, view.height)
        return Qt.point(
            Math.max(topLeft.x, Math.min(bottomRight.x, contentX)),
            Math.max(topLeft.y, Math.min(bottomRight.y, contentY))
        )
    }

    function rowsInsideSelectionRect(view, left, top, right, bottom) {
        const a = contentArea.mapToItem(view, left, top)
        const b = contentArea.mapToItem(view, right, bottom)
        const x1 = Math.min(a.x, b.x)
        const y1 = Math.min(a.y, b.y)
        const x2 = Math.max(a.x, b.x)
        const y2 = Math.max(a.y, b.y)
        const rows = []

        for (let row = 0; row < view.count; ++row) {
            const item = view.itemAtIndex(row)
            if (!item || !item.visible)
                continue
            const point = item.mapToItem(view, 0, 0)
            if (point.x + item.width < x1 || point.x > x2
                    || point.y + item.height < y1 || point.y > y2)
                continue
            rows.push(row)
        }
        return rows
    }

    function beginBackgroundSelection(view, contentX, contentY, modifiers) {
        selectionDragPending = true
        selectionDragActive = false
        selectionDragAdditive = (modifiers & Qt.ControlModifier) !== 0
        selectionDragBaseline = selectionDragAdditive ? selectedIndexes.slice() : []
        const point = clampContentPointToView(view, contentX, contentY)
        selectionDragStartX = point.x
        selectionDragStartY = point.y
        selectionDragCurrentX = point.x
        selectionDragCurrentY = point.y
        if (!selectionDragAdditive)
            clearSelection()
    }

    function updateBackgroundSelection(view, contentX, contentY) {
        if (!selectionDragPending)
            return

        const point = clampContentPointToView(view, contentX, contentY)
        selectionDragCurrentX = point.x
        selectionDragCurrentY = point.y
        const dx = selectionDragCurrentX - selectionDragStartX
        const dy = selectionDragCurrentY - selectionDragStartY
        if (!selectionDragActive && Math.sqrt(dx * dx + dy * dy) < 5)
            return

        selectionDragActive = true
        const hits = rowsInsideSelectionRect(
            view,
            Math.min(selectionDragStartX, selectionDragCurrentX),
            Math.min(selectionDragStartY, selectionDragCurrentY),
            Math.max(selectionDragStartX, selectionDragCurrentX),
            Math.max(selectionDragStartY, selectionDragCurrentY)
        )
        const merged = selectionDragAdditive ? selectionDragBaseline.concat(hits) : hits
        applySelection(
            merged,
            hits.length > 0 ? hits[hits.length - 1]
                            : (selectionDragBaseline.length > 0
                                ? selectionDragBaseline[selectionDragBaseline.length - 1] : -1),
            true
        )
    }

    function endBackgroundSelection() {
        if (selectionDragActive && selectedIndex >= 0)
            selectionAnchor = selectedIndex

        // Commit the finished marquee selection before releasing pointer
        // ownership. This keeps the selection alive after M1 is released and
        // synchronizes native drag-out with the exact persistent group.
        directoryModel.setSelectedRows(selectedIndexes.slice())
        selectionDragPending = false
        selectionDragActive = false
        selectionDragBaseline = []
    }

    // Scale wheel travel by the amount of content that actually remains to
    // scroll. Short folders stay precise; very deep folders cover more ground
    // per notch. Pixel-delta touchpads receive only a softened multiplier.
    function adaptiveScrollMultiplier(view) {
        const viewport = Math.max(1, view.height)
        const scrollRange = Math.max(0, view.contentHeight - viewport)
        if (scrollRange <= 1)
            return 0.80

        const pages = scrollRange / viewport
        const scaled = 0.80 + 0.50 * (Math.log(1 + pages) / Math.LN2)
        return Math.max(0.80, Math.min(3.20, scaled))
    }

    function boundedContentY(view, targetY) {
        const minimum = Number.isFinite(view.originY) ? view.originY : 0
        const maximum = Math.max(minimum, minimum + view.contentHeight - view.height)
        return Math.max(minimum, Math.min(maximum, targetY))
    }

    function handleAdaptiveWheel(view, wheel, baseStep, animation) {
        const multiplier = adaptiveScrollMultiplier(view)
        const pixelY = wheel.pixelDelta ? wheel.pixelDelta.y : 0

        if (Math.abs(pixelY) > 0.5) {
            animation.stop()
            const touchFactor = Math.min(1.80, Math.sqrt(multiplier))
            view.contentY = boundedContentY(view,
                view.contentY - pixelY * touchFactor)
            wheel.accepted = true
            return
        }

        const notch = wheel.angleDelta ? wheel.angleDelta.y / 120 : 0
        if (Math.abs(notch) < 0.01)
            return

        const targetY = boundedContentY(view,
            view.contentY - notch * baseStep * multiplier)
        animation.stop()
        animation.from = view.contentY
        animation.to = targetY
        animation.start()
        wheel.accepted = true
    }

    function handleBrowseKey(event) {
        if (event.accepted || root.textEntryHasFocus() || namePopup.opened
                || morePopup.opened || contextPopup.opened || backgroundPopup.opened)
            return

        if (event.key === Qt.Key_Escape && root.searchVisible) {
            root.closeSearch()
            event.accepted = true
            return
        }

        const blockedModifiers = Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
        if ((event.modifiers & blockedModifiers) !== 0)
            return

        const typed = String(event.text || "")
        if (typed.length === 0 || typed.charCodeAt(0) < 0x20
                || typed.charCodeAt(0) === 0x7f)
            return

        if (!root.searchVisible)
            searchField.text = typed
        else
            searchField.text += typed
        root.searchVisible = true
        directoryModel.searchQuery = searchField.text
        event.accepted = true

        Qt.callLater(function() {
            searchField.forceActiveFocus()
            searchField.cursorPosition = searchField.text.length
        })
    }

    readonly property color familyShell: mix(surfaceElevated, baseBackground, lightMode ? 0.28 : 0.48)
    readonly property color shellFill: alpha(familyShell, lightMode ? 0.72 : 0.60)
    readonly property color sidebarFill: alpha(mix(surfaceElevated, baseBackground, 0.55), lightMode ? 0.48 : 0.42)
    readonly property color toolbarFill: alpha(mix(surfaceElevated, baseBackground, 0.44), lightMode ? 0.38 : 0.30)
    readonly property color contentFill: alpha(mix(surface, baseBackground, 0.62), lightMode ? 0.26 : 0.18)
    readonly property color menuFill: alpha(mix(surfaceElevated, baseBackground, 0.36), lightMode ? 0.91 : 0.88)
    readonly property color hoverFill: alpha(foreground, lightMode ? 0.075 : 0.055)
    readonly property color selectedFill: alpha(mix(surfaceElevated, accent, 0.22), lightMode ? 0.54 : 0.48)
    readonly property color selectedRim: alpha(accent, 0.20)
    readonly property color quietRim: alpha(foreground, lightMode ? 0.13 : 0.095)
    readonly property color divider: alpha(foreground, lightMode ? 0.10 : 0.065)

    component ToolbarGlyph: Canvas {
        id: glyphCanvas
        required property string symbol
        property color strokeColor: root.foreground

        implicitWidth: 20
        implicitHeight: 20
        width: implicitWidth
        height: implicitHeight
        antialiasing: true

        onStrokeColorChanged: requestPaint()
        onSymbolChanged: requestPaint()

        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = strokeColor
            ctx.fillStyle = strokeColor
            ctx.lineWidth = 1.8
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            if (symbol === "back") {
                ctx.beginPath()
                ctx.moveTo(12.5, 4.5)
                ctx.lineTo(6.5, 10)
                ctx.lineTo(12.5, 15.5)
                ctx.stroke()
            } else if (symbol === "forward") {
                ctx.beginPath()
                ctx.moveTo(7.5, 4.5)
                ctx.lineTo(13.5, 10)
                ctx.lineTo(7.5, 15.5)
                ctx.stroke()
            } else if (symbol === "up") {
                ctx.beginPath()
                ctx.moveTo(5, 12.5)
                ctx.lineTo(10, 7)
                ctx.lineTo(15, 12.5)
                ctx.stroke()
            } else if (symbol === "home") {
                ctx.beginPath()
                ctx.moveTo(4.5, 9.5)
                ctx.lineTo(10, 4.8)
                ctx.lineTo(15.5, 9.5)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(6.2, 8.4)
                ctx.lineTo(6.2, 15.3)
                ctx.lineTo(13.8, 15.3)
                ctx.lineTo(13.8, 8.4)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(9, 15.2)
                ctx.lineTo(9, 11.6)
                ctx.lineTo(11, 11.6)
                ctx.lineTo(11, 15.2)
                ctx.stroke()
            } else if (symbol === "search") {
                ctx.beginPath()
                ctx.arc(8.4, 8.4, 4.5, 0, Math.PI * 2)
                ctx.stroke()
                ctx.beginPath()
                ctx.moveTo(11.8, 11.8)
                ctx.lineTo(16, 16)
                ctx.stroke()
            } else if (symbol === "list") {
                for (let y of [5.5, 10, 14.5]) {
                    ctx.beginPath()
                    ctx.arc(4.7, y, 0.9, 0, Math.PI * 2)
                    ctx.fill()
                    ctx.beginPath()
                    ctx.moveTo(7.5, y)
                    ctx.lineTo(15.5, y)
                    ctx.stroke()
                }
            } else if (symbol === "grid") {
                ctx.lineWidth = 1.6
                ctx.strokeRect(4.2, 4.2, 4.5, 4.5)
                ctx.strokeRect(11.3, 4.2, 4.5, 4.5)
                ctx.strokeRect(4.2, 11.3, 4.5, 4.5)
                ctx.strokeRect(11.3, 11.3, 4.5, 4.5)
            } else if (symbol === "more") {
                for (let x of [5.2, 10, 14.8]) {
                    ctx.beginPath()
                    ctx.arc(x, 10, 1.25, 0, Math.PI * 2)
                    ctx.fill()
                }
            }
        }
    }

    component IconButton: Rectangle {
        id: button
        property string iconName: ""
        property string glyph: ""
        property bool enabledState: true
        property bool activeState: false
        property string tooltip: ""
        signal triggered()

        implicitWidth: 38
        implicitHeight: 38
        width: implicitWidth
        height: implicitHeight
        radius: 13
        color: activeState
            ? root.alpha(root.accent, root.lightMode ? 0.15 : 0.12)
            : buttonHover.hovered && enabledState ? root.hoverFill : "transparent"
        border.width: activeState ? 1 : 0
        border.color: root.alpha(root.accent, 0.22)
        opacity: enabledState ? 1 : 0.30
        scale: buttonTap.pressed ? 0.94 : 1

        Behavior on color { ColorAnimation { duration: 145 } }
        Behavior on scale { NumberAnimation { duration: 105; easing.type: Easing.OutCubic } }

        ToolbarGlyph {
            anchors.centerIn: parent
            symbol: button.glyph
            visible: button.glyph.length > 0
            opacity: button.enabledState ? 0.96 : 0.48
        }

        Image {
            anchors.centerIn: parent
            width: 18
            height: 18
            visible: button.glyph.length === 0 && button.iconName.length > 0
            sourceSize: Qt.size(36, 36)
            source: visible ? root.icon(button.iconName) : ""
            opacity: button.enabledState ? 0.92 : 0.48
            smooth: true
            mipmap: true
        }

        HoverHandler { id: buttonHover }
        TapHandler {
            id: buttonTap
            enabled: button.enabledState
            onTapped: button.triggered()
        }

        ToolTip.visible: buttonHover.hovered && button.tooltip.length > 0
        ToolTip.text: button.tooltip
        ToolTip.delay: 500
    }

    component MenuAction: Item {
        id: menuAction
        required property string label
        property string iconName: ""
        property bool enabledState: true
        property bool destructive: false
        property bool checkedState: false
        signal triggered()

        width: 226
        height: 38
        opacity: enabledState ? 1 : 0.38

        Rectangle {
            anchors.fill: parent
            radius: 11
            color: menuHover.hovered && menuAction.enabledState ? root.hoverFill : "transparent"
            Behavior on color { ColorAnimation { duration: 120 } }
        }

        Image {
            id: menuIcon
            visible: menuAction.iconName.length > 0
            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 17
            height: 17
            sourceSize: Qt.size(34, 34)
            source: visible ? root.icon(menuAction.iconName) : ""
            opacity: 0.86
            smooth: true
            mipmap: true
        }

        Text {
            anchors.left: menuIcon.visible ? menuIcon.right : parent.left
            anchors.leftMargin: menuIcon.visible ? 10 : 12
            anchors.right: checkMark.visible ? checkMark.left : parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            text: menuAction.label
            color: menuAction.destructive ? root.mix(root.foreground, root.accent, 0.55) : root.foreground
            font.pixelSize: 13
            elide: Text.ElideRight
        }

        Text {
            id: checkMark
            visible: menuAction.checkedState
            anchors.right: parent.right
            anchors.rightMargin: 11
            anchors.verticalCenter: parent.verticalCenter
            text: "✓"
            color: root.accent
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }

        HoverHandler { id: menuHover }
        TapHandler {
            enabled: menuAction.enabledState
            onTapped: menuAction.triggered()
        }
    }

    component CompactActionButton: Rectangle {
        id: compactButton
        required property string label
        property bool primary: false
        signal triggered()

        implicitWidth: Math.max(76, compactLabel.implicitWidth + 28)
        implicitHeight: 36
        radius: 12
        color: compactButton.primary
            ? root.alpha(root.accent, compactHover.hovered ? 0.22 : 0.16)
            : compactHover.hovered ? root.hoverFill : root.alpha(root.foreground, 0.035)
        border.width: 1
        border.color: compactButton.primary ? root.alpha(root.accent, 0.28) : root.alpha(root.foreground, 0.08)
        scale: compactTap.pressed ? 0.96 : 1

        Text {
            id: compactLabel
            anchors.centerIn: parent
            text: compactButton.label
            color: root.foreground
            font.pixelSize: 12
            font.weight: compactButton.primary ? Font.DemiBold : Font.Normal
        }

        HoverHandler { id: compactHover }
        TapHandler {
            id: compactTap
            onTapped: compactButton.triggered()
        }
    }

    component WindowResizeHandle: Item {
        id: resizeHandle
        required property int edges
        required property int resizeCursor
        z: 1000

        HoverHandler { cursorShape: resizeHandle.resizeCursor }
        DragHandler {
            target: null
            acceptedButtons: Qt.LeftButton
            onActiveChanged: {
                if (active)
                    root.startSystemResize(resizeHandle.edges)
            }
        }
    }

    Shortcut { sequence: "Alt+Left"; onActivated: directoryModel.goBack() }
    Shortcut { sequence: "Alt+Right"; onActivated: directoryModel.goForward() }
    Shortcut { sequence: "Alt+Up"; onActivated: directoryModel.goUp() }
    Shortcut { sequence: "Ctrl+L"; onActivated: { pathField.forceActiveFocus(); pathField.selectAll() } }
    Shortcut { sequence: "Ctrl+F"; onActivated: root.showSearch() }
    Shortcut { sequence: "Ctrl+H"; onActivated: directoryModel.showHidden = !directoryModel.showHidden }
    Shortcut { sequence: "Ctrl+Shift+R"; onActivated: directoryModel.goRecent() }
    Shortcut { sequence: "Ctrl+Shift+N"; onActivated: namePopup.beginNewFolder() }
    Shortcut { sequence: "F5"; onActivated: directoryModel.reload() }
    Shortcut { sequence: "F2"; enabled: root.selectedCount === 1; onActivated: namePopup.beginRename(root.selectedIndex) }
    Shortcut {
        sequence: "Delete"
        enabled: root.selectedCount > 0
        onActivated: {
            directoryModel.trashRows(root.selectedIndexes)
            root.clearSelection()
        }
    }
    Shortcut {
        sequence: "Shift+Delete"
        enabled: root.selectedCount > 0
        onActivated: deletePopup.confirmRows(root.selectedIndexes)
    }
    Shortcut { sequence: "Ctrl+C"; enabled: root.selectedCount > 0; onActivated: directoryModel.copyRows(root.selectedIndexes, false) }
    Shortcut { sequence: "Ctrl+X"; enabled: root.selectedCount > 0; onActivated: directoryModel.copyRows(root.selectedIndexes, true) }
    Shortcut { sequence: "Ctrl+V"; enabled: directoryModel.canPaste; onActivated: directoryModel.paste() }
    Shortcut { sequence: "Ctrl+A"; enabled: !root.textEntryHasFocus(); onActivated: root.selectAllVisibleModelRows() }

    Connections {
        target: directoryModel
        function onCurrentUrlChanged() {
            root.clearSelection()
            if (!pathField.activeFocus)
                pathField.text = directoryModel.displayPath
        }
        function onModelReset() {
            root.clearSelection()
        }
        function onSearchQueryChanged() {
            if (!searchField.activeFocus)
                searchField.text = directoryModel.searchQuery
        }
        function onSelectRowRequested(row) {
            root.selectSingle(row)
            Qt.callLater(function() {
                if (root.viewMode === "grid")
                    grid.positionViewAtIndex(row, GridView.Contain)
                else
                    listView.positionViewAtIndex(row, ListView.Contain)
            })
        }
        function onPropertiesReady(details, iconName) {
            if (!propertiesPopup.opened)
                return
            propertiesPopup.details = details
            propertiesPopup.iconName = iconName
        }
    }

    Popup {
        id: morePopup
        parent: Overlay.overlay
        padding: 8
        width: Math.min(242, Math.max(220, root.width - 24))
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        function openBelow(item) {
            const point = item.mapToItem(root.contentItem, item.width, item.height + 7)
            x = Math.max(12, Math.min(root.width - width - 12, point.x - width))
            y = Math.max(12, Math.min(root.height - height - 12, point.y))
            open()
        }

        background: Rectangle {
            radius: 18
            color: root.menuFill
            border.width: 1
            border.color: root.quietRim
        }

        contentItem: Column {
            spacing: 2

            MenuAction {
                label: "New Folder"
                iconName: "folder-new"
                enabledState: directoryModel.canMutateCurrentDirectory
                onTriggered: { morePopup.close(); namePopup.beginNewFolder() }
            }
            MenuAction {
                label: "New File"
                iconName: "document-new"
                enabledState: directoryModel.canMutateCurrentDirectory
                onTriggered: { morePopup.close(); namePopup.beginNewFile() }
            }
            MenuAction {
                label: "Paste"
                iconName: "edit-paste"
                enabledState: directoryModel.canPaste
                onTriggered: { morePopup.close(); directoryModel.paste() }
            }
            Rectangle { width: Math.min(226, morePopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: root.searchVisible ? "Hide Search" : "Search This Folder"
                iconName: "edit-find"
                checkedState: root.searchVisible
                onTriggered: {
                    morePopup.close()
                    if (root.searchVisible) {
                        root.searchVisible = false
                        directoryModel.searchQuery = ""
                    } else {
                        root.showSearch()
                    }
                }
            }
            MenuAction {
                label: directoryModel.showHidden ? "Hide Hidden Files" : "Show Hidden Files"
                iconName: "view-hidden"
                checkedState: directoryModel.showHidden
                onTriggered: { morePopup.close(); directoryModel.showHidden = !directoryModel.showHidden }
            }
            MenuAction {
                label: root.viewMode === "grid" ? "Switch to List View" : "Switch to Grid View"
                iconName: root.viewMode === "grid" ? "view-list-details" : "view-grid"
                onTriggered: {
                    morePopup.close()
                    root.viewMode = root.viewMode === "grid" ? "list" : "grid"
                }
            }
            Rectangle { width: Math.min(226, morePopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: "Sort by Name"
                enabledState: directoryModel.searchQuery.length === 0
                    && String(directoryModel.currentUrl).indexOf("timeline:") !== 0
                iconName: "view-sort-ascending"
                checkedState: directoryModel.sortKey === "name"
                onTriggered: { directoryModel.sortKey = "name" }
            }
            MenuAction {
                label: "Sort by Modified"
                enabledState: directoryModel.searchQuery.length === 0
                    && String(directoryModel.currentUrl).indexOf("timeline:") !== 0
                iconName: "view-sort-ascending"
                checkedState: directoryModel.sortKey === "modified"
                onTriggered: { directoryModel.sortKey = "modified" }
            }
            MenuAction {
                label: "Sort by Size"
                enabledState: directoryModel.searchQuery.length === 0
                    && String(directoryModel.currentUrl).indexOf("timeline:") !== 0
                iconName: "view-sort-ascending"
                checkedState: directoryModel.sortKey === "size"
                onTriggered: { directoryModel.sortKey = "size" }
            }
            MenuAction {
                label: "Sort by Type"
                enabledState: directoryModel.searchQuery.length === 0
                    && String(directoryModel.currentUrl).indexOf("timeline:") !== 0
                iconName: "view-sort-ascending"
                checkedState: directoryModel.sortKey === "type"
                onTriggered: { directoryModel.sortKey = "type" }
            }
            MenuAction {
                label: "Reverse Sort Order"
                enabledState: directoryModel.searchQuery.length === 0
                    && String(directoryModel.currentUrl).indexOf("timeline:") !== 0
                iconName: "view-sort-descending"
                checkedState: directoryModel.sortDescending
                onTriggered: { directoryModel.sortDescending = !directoryModel.sortDescending }
            }
            Rectangle { width: Math.min(226, morePopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: "Reload"
                iconName: "view-refresh"
                onTriggered: { morePopup.close(); directoryModel.reload() }
            }
        }
    }

    Popup {
        id: contextPopup
        parent: Overlay.overlay
        padding: 8
        width: Math.min(242, Math.max(220, root.width - 24))
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        property int targetIndex: -1

        function openFor(index, item) {
            targetIndex = index
            if (!root.isSelected(index))
                root.selectSingle(index)
            const point = item.mapToItem(root.contentItem, Math.min(item.width - 12, 110), 28)
            x = Math.max(12, Math.min(root.width - width - 12, point.x))
            y = Math.max(12, Math.min(root.height - height - 12, point.y))
            open()
        }

        background: Rectangle {
            radius: 18
            color: root.menuFill
            border.width: 1
            border.color: root.quietRim
        }

        contentItem: Column {
            spacing: 2

            MenuAction {
                label: "Open"
                iconName: "document-open"
                onTriggered: { contextPopup.close(); directoryModel.openIndex(contextPopup.targetIndex) }
            }
            MenuAction {
                label: "Rename"
                iconName: "edit-rename"
                enabledState: root.selectedCount === 1
                onTriggered: { const row = contextPopup.targetIndex; contextPopup.close(); namePopup.beginRename(row) }
            }
            MenuAction {
                label: "Open With…"
                iconName: "system-run"
                enabledState: root.selectedCount === 1
                onTriggered: { contextPopup.close(); directoryModel.openWithIndex(contextPopup.targetIndex) }
            }
            MenuAction {
                label: "Properties"
                iconName: "document-properties"
                enabledState: root.selectedCount === 1
                onTriggered: {
                    const row = contextPopup.targetIndex
                    propertiesPopup.details = directoryModel.propertiesText(row)
                    propertiesPopup.iconName = directoryModel.iconNameAt(row)
                    contextPopup.close()
                    propertiesPopup.open()
                    directoryModel.requestProperties(row)
                }
            }
            Rectangle { width: Math.min(226, contextPopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: root.selectedCount > 1 ? "Copy " + root.selectedCount + " Items" : "Copy"
                iconName: "edit-copy"
                onTriggered: { contextPopup.close(); directoryModel.copyRows(root.selectedIndexes, false) }
            }
            MenuAction {
                label: root.selectedCount > 1 ? "Cut " + root.selectedCount + " Items" : "Cut"
                iconName: "edit-cut"
                onTriggered: { contextPopup.close(); directoryModel.copyRows(root.selectedIndexes, true) }
            }
            MenuAction {
                label: root.selectedCount > 1 ? "Duplicate " + root.selectedCount + " Items" : "Duplicate"
                iconName: "edit-copy"
                enabledState: root.selectedCount > 0
                onTriggered: { contextPopup.close(); directoryModel.duplicateRows(root.selectedIndexes) }
            }
            MenuAction {
                label: "Copy Path"
                iconName: "edit-copy-path"
                enabledState: root.selectedCount === 1
                onTriggered: { contextPopup.close(); directoryModel.copyPathIndex(contextPopup.targetIndex) }
            }
            MenuAction {
                label: "Paste Here"
                iconName: "edit-paste"
                enabledState: directoryModel.canPaste
                onTriggered: { contextPopup.close(); directoryModel.paste() }
            }
            Rectangle { width: Math.min(226, contextPopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: root.selectedCount > 1 ? "Move " + root.selectedCount + " Items to Trash" : "Move to Trash"
                iconName: "user-trash"
                destructive: true
                onTriggered: {
                    contextPopup.close()
                    directoryModel.trashRows(root.selectedIndexes)
                    root.clearSelection()
                }
            }
            MenuAction {
                label: root.selectedCount > 1
                    ? "Delete " + root.selectedCount + " Items Permanently…"
                    : "Delete Permanently…"
                iconName: "edit-delete"
                destructive: true
                onTriggered: {
                    contextPopup.close()
                    deletePopup.confirmRows(root.selectedIndexes)
                }
            }
        }
    }

    Popup {
        id: backgroundPopup
        parent: Overlay.overlay
        padding: 8
        width: Math.min(242, Math.max(220, root.width - 24))
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        function openAt(contentX, contentY) {
            const point = contentArea.mapToItem(root.contentItem, contentX, contentY)
            x = Math.max(12, Math.min(root.width - width - 12, point.x))
            y = Math.max(12, Math.min(root.height - height - 12, point.y))
            open()
        }

        background: Rectangle {
            radius: 18
            color: root.menuFill
            border.width: 1
            border.color: root.quietRim
        }

        contentItem: Column {
            spacing: 2

            MenuAction {
                label: "New Folder"
                iconName: "folder-new"
                enabledState: directoryModel.canMutateCurrentDirectory
                onTriggered: { backgroundPopup.close(); namePopup.beginNewFolder() }
            }
            MenuAction {
                label: "New File"
                iconName: "document-new"
                enabledState: directoryModel.canMutateCurrentDirectory
                onTriggered: { backgroundPopup.close(); namePopup.beginNewFile() }
            }
            MenuAction {
                label: "Paste"
                iconName: "edit-paste"
                enabledState: directoryModel.canPaste && directoryModel.canMutateCurrentDirectory
                onTriggered: { backgroundPopup.close(); directoryModel.paste() }
            }
            Rectangle { width: Math.min(226, backgroundPopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: root.searchVisible ? "Hide Search" : "Search This Folder"
                iconName: "edit-find"
                checkedState: root.searchVisible
                onTriggered: {
                    backgroundPopup.close()
                    if (root.searchVisible)
                        root.closeSearch()
                    else
                        root.showSearch()
                }
            }
            MenuAction {
                label: directoryModel.showHidden ? "Hide Hidden Files" : "Show Hidden Files"
                iconName: "view-hidden"
                checkedState: directoryModel.showHidden
                onTriggered: {
                    backgroundPopup.close()
                    directoryModel.showHidden = !directoryModel.showHidden
                }
            }
            MenuAction {
                label: root.viewMode === "grid" ? "Switch to List View" : "Switch to Grid View"
                iconName: root.viewMode === "grid" ? "view-list-details" : "view-grid"
                onTriggered: {
                    backgroundPopup.close()
                    root.viewMode = root.viewMode === "grid" ? "list" : "grid"
                }
            }
            Rectangle { width: Math.min(226, backgroundPopup.width - 16); height: 1; color: root.divider }
            MenuAction {
                label: "Reload"
                iconName: "view-refresh"
                onTriggered: { backgroundPopup.close(); directoryModel.reload() }
            }
        }
    }

    Popup {
        id: propertiesPopup
        parent: Overlay.overlay
        modal: true
        focus: true
        padding: 18
        width: Math.min(440, Math.max(300, root.width - 24))
        anchors.centerIn: Overlay.overlay
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        property string details: ""
        property string iconName: "unknown"
        onClosed: directoryModel.cancelProperties()

        background: Rectangle {
            radius: 22
            color: root.menuFill
            border.width: 1
            border.color: root.quietRim
        }

        contentItem: ColumnLayout {
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Image {
                    Layout.preferredWidth: 38
                    Layout.preferredHeight: 38
                    sourceSize: Qt.size(76, 76)
                    source: root.icon(propertiesPopup.iconName)
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }

                Text {
                    Layout.fillWidth: true
                    text: "Properties"
                    color: root.foreground
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                }
            }

            Text {
                Layout.fillWidth: true
                text: propertiesPopup.details
                color: root.alpha(root.foreground, 0.86)
                font.pixelSize: 12
                wrapMode: Text.Wrap
                lineHeight: 1.25
            }
        }
    }

    Popup {
        id: deletePopup
        parent: Overlay.overlay
        modal: true
        focus: true
        padding: 18
        width: Math.min(410, Math.max(290, root.width - 24))
        anchors.centerIn: Overlay.overlay
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        property string token: ""
        property var names: []

        function confirmRows(selectedRows) {
            const rows = root.normalizedIndexes(selectedRows)
            if (rows.length === 0)
                return
            const request = directoryModel.preparePermanentDelete(rows)
            const preparedToken = String(request.token || "")
            if (preparedToken === "")
                return
            token = preparedToken
            names = request.names || []
            open()
        }

        function targetSummary() {
            if (names.length <= 1)
                return ""
            const shown = []
            const limit = Math.min(names.length, 4)
            for (let i = 0; i < limit; ++i)
                shown.push(String(names[i]))
            if (names.length > limit)
                shown.push("…")
            return shown.join("  ·  ")
        }

        onClosed: {
            if (token !== "")
                directoryModel.cancelPermanentDelete(token)
            token = ""
            names = []
        }

        background: Rectangle {
            radius: 22
            color: root.menuFill
            border.width: 1
            border.color: root.quietRim
        }

        contentItem: ColumnLayout {
            spacing: 14

            Image {
                Layout.alignment: Qt.AlignHCenter
                Layout.preferredWidth: 42
                Layout.preferredHeight: 42
                sourceSize: Qt.size(84, 84)
                source: root.icon("edit-delete")
            }

            Text {
                Layout.fillWidth: true
                text: deletePopup.names.length === 1
                    ? "Permanently delete “" + String(deletePopup.names[0]) + "”?"
                    : "Permanently delete " + deletePopup.names.length + " items?"
                color: root.foreground
                font.pixelSize: 16
                font.weight: Font.DemiBold
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }

            Text {
                Layout.fillWidth: true
                visible: deletePopup.names.length > 1
                text: deletePopup.targetSummary()
                color: root.alpha(root.muted, 0.70)
                font.pixelSize: 11
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }

            Text {
                Layout.fillWidth: true
                text: "This is different from Trash and cannot be undone."
                color: root.alpha(root.muted, 0.82)
                font.pixelSize: 12
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8
                CompactActionButton { label: "Cancel"; onTriggered: deletePopup.close() }
                CompactActionButton {
                    label: "Delete"
                    primary: true
                    onTriggered: {
                        const confirmationToken = deletePopup.token
                        deletePopup.token = ""
                        deletePopup.names = []
                        deletePopup.close()
                        directoryModel.confirmPermanentDelete(confirmationToken)
                        root.clearSelection()
                    }
                }
            }
        }
    }

    Popup {
        id: namePopup
        parent: Overlay.overlay
        modal: true
        focus: true
        padding: 18
        width: Math.min(380, Math.max(280, root.width - 24))
        height: 178
        anchors.centerIn: Overlay.overlay
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property string mode: "folder"
        property int targetIndex: -1

        function beginNewFolder() {
            mode = "folder"
            targetIndex = -1
            nameField.text = "New Folder"
            open()
            Qt.callLater(function() { nameField.forceActiveFocus(); nameField.selectAll() })
        }

        function beginNewFile() {
            mode = "file"
            targetIndex = -1
            nameField.text = "New File"
            open()
            Qt.callLater(function() { nameField.forceActiveFocus(); nameField.selectAll() })
        }

        function beginRename(row) {
            if (row < 0)
                return
            mode = "rename"
            targetIndex = row
            nameField.text = directoryModel.nameAt(row)
            open()
            Qt.callLater(function() { nameField.forceActiveFocus(); nameField.selectAll() })
        }

        function submit() {
            if (mode === "folder")
                directoryModel.createFolder(nameField.text)
            else if (mode === "file")
                directoryModel.createFile(nameField.text)
            else
                directoryModel.renameIndex(targetIndex, nameField.text)
            close()
        }

        background: Rectangle {
            radius: 22
            color: root.menuFill
            border.width: 1
            border.color: root.quietRim
        }

        contentItem: ColumnLayout {
            spacing: 12

            Text {
                Layout.fillWidth: true
                text: namePopup.mode === "folder"
                    ? "New Folder"
                    : namePopup.mode === "file" ? "New File" : "Rename"
                color: root.foreground
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 42
                radius: 13
                color: root.alpha(root.surfaceElevated, root.lightMode ? 0.50 : 0.38)
                border.width: 1
                border.color: nameField.activeFocus ? root.alpha(root.accent, 0.30) : root.alpha(root.foreground, 0.08)

                TextField {
                    id: nameField
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    color: root.foreground
                    selectByMouse: true
                    background: Item {}
                    Keys.onReturnPressed: namePopup.submit()
                }
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 8
                CompactActionButton { label: "Cancel"; onTriggered: namePopup.close() }
                CompactActionButton {
                    label: namePopup.mode === "rename" ? "Rename" : "Create"
                    primary: true
                    onTriggered: namePopup.submit()
                }
            }
        }
    }

    Rectangle {
        id: shell
        anchors.fill: parent
        anchors.margins: 1
        radius: Math.min(28, Math.max(18, Math.min(root.width, root.height) * 0.06))
        color: root.shellFill
        border.width: 1
        border.color: root.quietRim
        clip: true

        Keys.onPressed: function(event) { root.handleBrowseKey(event) }

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
                Layout.preferredHeight: root.height < 360 ? 58 : 72
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
                    anchors.leftMargin: root.tinyToolbar ? 8 : 16
                    anchors.rightMargin: root.tinyToolbar ? 8 : 16
                    spacing: root.tinyToolbar ? 2 : 6

                    IconButton {
                        glyph: "back"
                        tooltip: "Back"
                        enabledState: directoryModel.canGoBack
                        onTriggered: directoryModel.goBack()
                    }
                    IconButton {
                        glyph: "forward"
                        tooltip: "Forward"
                        enabledState: directoryModel.canGoForward
                        onTriggered: directoryModel.goForward()
                    }
                    IconButton {
                        glyph: "up"
                        tooltip: "Up one folder"
                        visible: !root.tinyToolbar
                        onTriggered: directoryModel.goUp()
                    }
                    IconButton {
                        glyph: "home"
                        tooltip: "Home"
                        visible: !root.tinyToolbar
                        onTriggered: directoryModel.goHome()
                    }

                    Rectangle {
                        Layout.leftMargin: root.tinyToolbar ? 2 : 7
                        Layout.fillWidth: true
                        Layout.minimumWidth: 64
                        Layout.preferredHeight: root.height < 360 ? 38 : 44
                        radius: 16
                        color: root.alpha(root.mix(root.surfaceElevated, root.baseBackground, 0.58), root.lightMode ? 0.48 : 0.40)
                        border.width: 1
                        border.color: pathField.activeFocus
                            ? root.alpha(root.accent, 0.28)
                            : root.alpha(root.foreground, 0.07)

                        Image {
                            anchors.left: parent.left
                            anchors.leftMargin: 13
                            anchors.verticalCenter: parent.verticalCenter
                            width: 17
                            height: 17
                            sourceSize: Qt.size(34, 34)
                            source: root.icon("folder-open")
                            opacity: 0.72
                            visible: parent.width >= 90
                        }

                        TextField {
                            id: pathField
                            anchors.fill: parent
                            anchors.leftMargin: parent.width >= 90 ? 38 : 10
                            anchors.rightMargin: 10
                            color: root.foreground
                            placeholderText: "Location"
                            placeholderTextColor: root.alpha(root.muted, 0.65)
                            font.pixelSize: 14
                            selectByMouse: true
                            background: Item {}

                            Component.onCompleted: text = directoryModel.displayPath
                            onActiveFocusChanged: {
                                if (activeFocus)
                                    selectAll()
                            }
                            onAccepted: {
                                directoryModel.openLocation(text)
                                focus = false
                            }
                        }
                    }

                    IconButton {
                        glyph: "search"
                        tooltip: "Search"
                        activeState: root.searchVisible
                        onTriggered: {
                            if (root.searchVisible) {
                                root.searchVisible = false
                                directoryModel.searchQuery = ""
                            } else {
                                root.showSearch()
                            }
                        }
                    }

                    IconButton {
                        glyph: root.viewMode === "grid" ? "list" : "grid"
                        tooltip: root.viewMode === "grid" ? "List view" : "Grid view"
                        visible: !root.tinyToolbar
                        onTriggered: root.viewMode = root.viewMode === "grid" ? "list" : "grid"
                    }

                    IconButton {
                        id: moreButton
                        glyph: "more"
                        tooltip: "More"
                        onTriggered: morePopup.openBelow(moreButton)
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: root.searchVisible ? Math.min(54, Math.max(42, root.height * 0.13)) : 0
                visible: root.searchVisible
                color: root.alpha(root.mix(root.surfaceElevated, root.baseBackground, 0.54), root.lightMode ? 0.30 : 0.24)
                clip: true

                Behavior on Layout.preferredHeight {
                    NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: root.divider
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: Math.max(180, Math.min(parent.width - 24, 620))
                    height: Math.min(38, parent.height - 8)
                    radius: 14
                    color: root.alpha(root.surfaceElevated, root.lightMode ? 0.42 : 0.32)
                    border.width: 1
                    border.color: searchField.activeFocus ? root.alpha(root.accent, 0.25) : root.alpha(root.foreground, 0.06)

                    Image {
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        width: 16
                        height: 16
                        source: root.icon("edit-find")
                        opacity: 0.70
                    }

                    TextField {
                        id: searchField
                        anchors.fill: parent
                        anchors.leftMargin: 36
                        anchors.rightMargin: 12
                        color: root.foreground
                        placeholderText: "Filter this folder"
                        placeholderTextColor: root.alpha(root.muted, 0.62)
                        background: Item {}
                        selectByMouse: true
                        onTextEdited: directoryModel.searchQuery = text
                        Keys.onEscapePressed: {
                            root.closeSearch()
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Rectangle {
                    Layout.preferredWidth: root.effectiveSidebarWidth
                    Layout.fillHeight: true
                    visible: !root.narrowWindow
                    color: root.sidebarFill

                    Item {
                        id: recentPlace
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        anchors.topMargin: 12
                        height: 40

                        property bool exactCurrent: String(directoryModel.currentUrl) === "timeline:/recent"

                        Rectangle {
                            anchors.fill: parent
                            radius: 12
                            color: recentPlace.exactCurrent
                                ? root.selectedFill
                                : recentHover.hovered ? root.hoverFill : "transparent"
                            border.width: recentPlace.exactCurrent ? 1 : 0
                            border.color: root.selectedRim
                        }

                        Row {
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 10
                            spacing: 9

                            Image {
                                width: 18
                                height: 18
                                sourceSize: Qt.size(36, 36)
                                source: root.icon("document-open-recent")
                            }

                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "Recent"
                                color: root.foreground
                                font.pixelSize: 13
                            }
                        }

                        HoverHandler { id: recentHover }
                        TapHandler { onTapped: directoryModel.goRecent() }
                    }

                    ListView {
                        id: placesView
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: recentPlace.bottom
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        anchors.topMargin: 4
                        anchors.bottomMargin: 12
                        clip: true
                        model: placesModel
                        spacing: 2
                        onContentHeightChanged: contentY = root.boundedContentY(placesView, contentY)
                        onHeightChanged: contentY = root.boundedContentY(placesView, contentY)

                        ScrollBar.vertical: MahoScrollBar {
                            id: placesScrollBar
                            viewMoving: placesView.moving
                            thumbColor: root.alpha(root.foreground, 0.24)
                            thumbHoverColor: root.alpha(root.accent, 0.42)
                            thumbPressedColor: root.alpha(root.accent, 0.68)
                            trackColor: root.alpha(root.foreground, 0.045)
                        }

                        WheelHandler {
                            target: null
                            blocking: false
                            onWheel: placesScrollBar.noteActivity()
                        }

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
                            property bool deviceActionAvailable: placesController.canEject(index) || placesController.canTeardown(index)
                            property bool dropReady: false

                            Rectangle {
                                anchors.fill: parent
                                radius: 12
                                color: placeDelegate.dropReady
                                    ? root.alpha(root.accent, root.lightMode ? 0.18 : 0.22)
                                    : placeDelegate.exactCurrent
                                        ? root.selectedFill
                                        : placeHover.hovered ? root.hoverFill : "transparent"
                                border.width: placeDelegate.exactCurrent || placeDelegate.dropReady ? 1 : 0
                                border.color: placeDelegate.dropReady
                                    ? root.alpha(root.accent, 0.72)
                                    : root.selectedRim
                                Behavior on color { ColorAnimation { duration: 145 } }
                            }

                            Row {
                                anchors.left: parent.left
                                anchors.right: deviceAction.left
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 10
                                anchors.rightMargin: 5
                                spacing: 9

                                Image {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: 18
                                    height: 18
                                    sourceSize: Qt.size(36, 36)
                                    source: root.icon(placeDelegate.iconName)
                                    smooth: true
                                    mipmap: true
                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    width: parent.width - 36
                                    text: placeDelegate.display
                                    color: root.foreground
                                    font.pixelSize: 13
                                    elide: Text.ElideRight
                                }
                            }

                            Rectangle {
                                id: deviceAction
                                anchors.right: parent.right
                                anchors.rightMargin: 5
                                anchors.verticalCenter: parent.verticalCenter
                                width: 26
                                height: 26
                                radius: 9
                                visible: placeDelegate.deviceActionAvailable || placesController.busyRow === placeDelegate.index
                                color: deviceHover.hovered ? root.hoverFill : "transparent"

                                Image {
                                    anchors.centerIn: parent
                                    width: 14
                                    height: 14
                                    source: root.icon("media-eject")
                                    visible: placesController.busyRow !== placeDelegate.index
                                    opacity: 0.72
                                }

                                BusyIndicator {
                                    anchors.centerIn: parent
                                    width: 18
                                    height: 18
                                    running: placesController.busyRow === placeDelegate.index
                                    visible: running
                                }

                                HoverHandler { id: deviceHover }
                                TapHandler {
                                    enabled: placesController.busyRow !== placeDelegate.index
                                    onTapped: {
                                        if (placesController.canEject(placeDelegate.index))
                                            placesController.eject(placeDelegate.index)
                                        else if (placesController.canTeardown(placeDelegate.index))
                                            placesController.teardown(placeDelegate.index)
                                    }
                                }
                            }

                            DropArea {
                                id: placeDrop
                                anchors.fill: parent
                                enabled: String(placeDelegate.url).length > 0
                                onEntered: function(drag) {
                                    placeDelegate.dropReady = root.acceptDrop(drag, placeDelegate.url)
                                }
                                onExited: placeDelegate.dropReady = false
                                onDropped: function(drop) {
                                    const accepted = root.performDrop(drop, placeDelegate.url)
                                    placeDelegate.dropReady = false
                                    if (!accepted)
                                        drop.accepted = false
                                }
                            }

                            HoverHandler { id: placeHover }
                            TapHandler {
                                acceptedButtons: Qt.LeftButton
                                enabled: !deviceHover.hovered
                                onTapped: placesController.activate(placeDelegate.index)
                            }
                        }
                    }
                }

                Item {
                    id: sidebarSplitter
                    Layout.preferredWidth: 7
                    Layout.fillHeight: true
                    visible: !root.narrowWindow
                    property real dragStartWidth: root.sidebarWidth

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: splitterHover.hovered || splitterDrag.active ? 2 : 1
                        color: splitterHover.hovered || splitterDrag.active
                            ? root.alpha(root.accent, 0.48)
                            : root.divider

                        Behavior on width { NumberAnimation { duration: 100 } }
                        Behavior on color { ColorAnimation { duration: 120 } }
                    }

                    HoverHandler {
                        id: splitterHover
                        cursorShape: Qt.SizeHorCursor
                    }

                    DragHandler {
                        id: splitterDrag
                        target: null
                        acceptedButtons: Qt.LeftButton
                        onActiveChanged: {
                            if (active)
                                sidebarSplitter.dragStartWidth = root.sidebarWidth
                        }
                        onTranslationChanged: {
                            if (active)
                                root.sidebarWidth = Math.max(180, Math.min(420, sidebarSplitter.dragStartWidth + translation.x))
                        }
                    }

                    TapHandler {
                        acceptedButtons: Qt.LeftButton
                        onDoubleTapped: root.sidebarWidth = 228
                    }
                }

                Rectangle {
                    id: contentArea
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: root.contentFill
                    clip: true

                    GridView {
                        id: grid
                        z: 2
                        anchors.fill: parent
                        anchors.margins: root.width < 560 ? 10 : 18
                        cellWidth: root.width < 560 ? 112 : root.width < 820 ? 124 : 138
                        cellHeight: root.width < 560 ? 116 : root.width < 820 ? 120 : 124
                        clip: true
                        visible: root.viewMode === "grid"
                        model: directoryModel
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: true
                        focus: visible

                        onContentHeightChanged: contentY = root.boundedContentY(grid, contentY)
                        onHeightChanged: contentY = root.boundedContentY(grid, contentY)

                        ScrollBar.vertical: MahoScrollBar {
                            id: gridScrollBar
                            viewMoving: grid.moving || gridWheelScroll.running
                            parent: contentArea
                            z: 90
                            anchors.top: grid.top
                            anchors.bottom: grid.bottom
                            anchors.right: grid.right
                            thumbColor: root.alpha(root.foreground, 0.24)
                            thumbHoverColor: root.alpha(root.accent, 0.44)
                            thumbPressedColor: root.alpha(root.accent, 0.72)
                            trackColor: root.alpha(root.foreground, 0.045)
                            onPressedChanged: {
                                if (pressed)
                                    gridWheelScroll.stop()
                            }
                        }

                        NumberAnimation {
                            id: gridWheelScroll
                            target: grid
                            property: "contentY"
                            duration: 105
                            easing.type: Easing.OutCubic
                        }

                        WheelHandler {
                            target: null
                            enabled: !gridScrollBar.pressed
                            blocking: true
                            onWheel: function(wheel) {
                                gridScrollBar.noteActivity()
                                root.handleAdaptiveWheel(
                                    grid,
                                    wheel,
                                    grid.cellHeight * 0.72,
                                    gridWheelScroll
                                )
                            }
                        }

                        delegate: Item {
                            id: fileDelegate
                            required property int index
                            required property string name
                            required property url url
                            required property string iconName
                            required property bool isDirectory
                            required property string mimeComment
                            required property string mimeType
                            required property url previewUrl

                            width: grid.cellWidth
                            height: grid.cellHeight
                            // Explicit native DnD identity. The full-content DropArea is
                            // visually above this delegate, so C++ must not infer rows
                            // from the topmost hit item.
                            property int mahoFileRow: index
                            property bool selected: root.isSelected(index)
                            property bool folderDropReady: false

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 3
                                radius: 18
                                color: fileDelegate.folderDropReady
                                    ? root.alpha(root.accent, root.lightMode ? 0.18 : 0.22)
                                    : fileDelegate.selected
                                        ? root.selectedFill
                                        : fileHover.hovered ? root.hoverFill : "transparent"
                                border.width: fileDelegate.selected || fileDelegate.folderDropReady ? 1 : 0
                                border.color: fileDelegate.folderDropReady
                                    ? root.alpha(root.accent, 0.72)
                                    : root.selectedRim
                                Behavior on color { ColorAnimation { duration: 145 } }
                            }

                            Column {
                                anchors.fill: parent
                                anchors.topMargin: 10
                                anchors.leftMargin: 8
                                anchors.rightMargin: 8
                                spacing: 7

                                Item {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: root.width < 560 ? 62 : 70
                                    height: width

                                    Rectangle {
                                        anchors.fill: parent
                                        radius: 12
                                        color: "transparent"
                                        clip: true
                                        visible: String(fileDelegate.previewUrl).length > 0

                                        Image {
                                            anchors.fill: parent
                                            source: fileDelegate.previewUrl
                                            sourceSize: Qt.size(140, 140)
                                            fillMode: Image.PreserveAspectCrop
                                            asynchronous: true
                                            smooth: true
                                        }
                                    }

                                    Image {
                                        anchors.centerIn: parent
                                        width: root.width < 560 ? 54 : 62
                                        height: width
                                        visible: String(fileDelegate.previewUrl).length === 0
                                        sourceSize: Qt.size(124, 124)
                                        source: root.icon(fileDelegate.iconName)
                                        fillMode: Image.PreserveAspectFit
                                        smooth: true
                                        mipmap: true
                                    }
                                }

                                Text {
                                    width: parent.width
                                    text: fileDelegate.name
                                    color: root.foreground
                                    horizontalAlignment: Text.AlignHCenter
                                    font.pixelSize: 12
                                    maximumLineCount: root.height < 330 ? 1 : 2
                                    wrapMode: Text.Wrap
                                    elide: Text.ElideRight
                                }
                            }

                            HoverHandler { id: fileHover }
                            DropArea {
                                id: gridFolderDrop
                                anchors.fill: parent
                                enabled: fileDelegate.isDirectory
                                onEntered: function(drag) {
                                    fileDelegate.folderDropReady = root.acceptDrop(drag, fileDelegate.url)
                                    if (fileDelegate.folderDropReady)
                                        root.folderDropTargetUrl = String(fileDelegate.url)
                                }
                                onExited: {
                                    fileDelegate.folderDropReady = false
                                    if (root.folderDropTargetUrl === String(fileDelegate.url))
                                        root.folderDropTargetUrl = ""
                                }
                                onDropped: function(drop) {
                                    const accepted = root.performDrop(drop, fileDelegate.url)
                                    fileDelegate.folderDropReady = false
                                    if (root.folderDropTargetUrl === String(fileDelegate.url))
                                        root.folderDropTargetUrl = ""
                                    if (!accepted)
                                        drop.accepted = false
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !root.contentScrollbarDragging
                                acceptedButtons: Qt.LeftButton
                                onClicked: function(mouse) {
                                    root.selectClicked(fileDelegate.index, mouse.modifiers)
                                }
                                onDoubleClicked: function(mouse) {
                                    root.selectSingle(fileDelegate.index)
                                    directoryModel.openIndex(fileDelegate.index)
                                    mouse.accepted = true
                                }
                            }
                            TapHandler {
                                acceptedButtons: Qt.RightButton
                                enabled: !root.contentScrollbarDragging
                                onTapped: contextPopup.openFor(fileDelegate.index, fileDelegate)
                            }
                        }

                        Keys.onReturnPressed: {
                            if (root.selectedIndex >= 0)
                                directoryModel.openIndex(root.selectedIndex)
                        }
                        Keys.onEnterPressed: {
                            if (root.selectedIndex >= 0)
                                directoryModel.openIndex(root.selectedIndex)
                        }
                    }

                    Item {
                        id: listPanel
                        z: 2
                        anchors.fill: parent
                        anchors.margins: root.width < 560 ? 8 : 16
                        visible: root.viewMode === "list"

                        Rectangle {
                            id: listHeader
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 38
                            radius: 12
                            color: root.alpha(root.foreground, 0.025)

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                spacing: 12

                                Text { Layout.fillWidth: true; text: "Name"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
                                Text { visible: contentArea.width >= 520; Layout.preferredWidth: 100; text: "Size"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
                                Text { visible: contentArea.width >= 700; Layout.preferredWidth: 150; text: "Type"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
                                Text { visible: contentArea.width >= 880; Layout.preferredWidth: 180; text: "Modified"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
                            }
                        }

                        ListView {
                            id: listView
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: listHeader.bottom
                            anchors.bottom: parent.bottom
                            anchors.topMargin: 4
                            clip: true
                            model: directoryModel
                            spacing: 1
                            focus: visible

                            onContentHeightChanged: contentY = root.boundedContentY(listView, contentY)
                            onHeightChanged: contentY = root.boundedContentY(listView, contentY)

                            ScrollBar.vertical: MahoScrollBar {
                                id: listScrollBar
                                viewMoving: listView.moving || listWheelScroll.running
                                z: 90
                                thumbColor: root.alpha(root.foreground, 0.24)
                                thumbHoverColor: root.alpha(root.accent, 0.44)
                                thumbPressedColor: root.alpha(root.accent, 0.72)
                                trackColor: root.alpha(root.foreground, 0.045)
                                onPressedChanged: {
                                    if (pressed)
                                        listWheelScroll.stop()
                                }
                            }

                            NumberAnimation {
                                id: listWheelScroll
                                target: listView
                                property: "contentY"
                                duration: 105
                                easing.type: Easing.OutCubic
                            }

                            WheelHandler {
                                target: null
                                enabled: !listScrollBar.pressed
                                blocking: true
                                onWheel: function(wheel) {
                                    listScrollBar.noteActivity()
                                    root.handleAdaptiveWheel(
                                        listView,
                                        wheel,
                                        88,
                                        listWheelScroll
                                    )
                                }
                            }

                            delegate: Item {
                                id: listDelegate
                                required property int index
                                required property string name
                                required property url url
                                required property bool isDirectory
                                required property string iconName
                                required property string sizeText
                                required property string mimeComment
                                required property string modifiedText
                                required property url previewUrl

                                width: listView.width
                                height: 44
                                property int mahoFileRow: index
                                property bool selected: root.isSelected(index)
                                property bool folderDropReady: false

                                Rectangle {
                                    anchors.fill: parent
                                    radius: 11
                                    color: listDelegate.folderDropReady
                                        ? root.alpha(root.accent, root.lightMode ? 0.18 : 0.22)
                                        : listDelegate.selected
                                            ? root.selectedFill
                                            : listHover.hovered ? root.hoverFill : "transparent"
                                    border.width: listDelegate.selected || listDelegate.folderDropReady ? 1 : 0
                                    border.color: listDelegate.folderDropReady
                                        ? root.alpha(root.accent, 0.72)
                                        : root.selectedRim
                                    Behavior on color { ColorAnimation { duration: 130 } }
                                }

                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 12
                                    anchors.rightMargin: 14
                                    spacing: 12

                                    RowLayout {
                                        Layout.fillWidth: true
                                        spacing: 10

                                        Image {
                                            Layout.preferredWidth: 24
                                            Layout.preferredHeight: 24
                                            sourceSize: Qt.size(48, 48)
                                            source: String(listDelegate.previewUrl).length > 0
                                                ? listDelegate.previewUrl
                                                : root.icon(listDelegate.iconName)
                                            fillMode: Image.PreserveAspectFit
                                            asynchronous: true
                                            smooth: true
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: listDelegate.name
                                            color: root.foreground
                                            font.pixelSize: 12
                                            elide: Text.ElideRight
                                        }
                                    }

                                    Text { visible: contentArea.width >= 520; Layout.preferredWidth: 100; text: listDelegate.sizeText; color: root.alpha(root.muted, 0.82); font.pixelSize: 11; elide: Text.ElideRight }
                                    Text { visible: contentArea.width >= 700; Layout.preferredWidth: 150; text: listDelegate.mimeComment; color: root.alpha(root.muted, 0.82); font.pixelSize: 11; elide: Text.ElideRight }
                                    Text { visible: contentArea.width >= 880; Layout.preferredWidth: 180; text: listDelegate.modifiedText; color: root.alpha(root.muted, 0.82); font.pixelSize: 11; elide: Text.ElideRight }
                                }

                                HoverHandler { id: listHover }
                                DropArea {
                                    id: listFolderDrop
                                    anchors.fill: parent
                                    enabled: listDelegate.isDirectory
                                    onEntered: function(drag) {
                                        listDelegate.folderDropReady = root.acceptDrop(drag, listDelegate.url)
                                        if (listDelegate.folderDropReady)
                                            root.folderDropTargetUrl = String(listDelegate.url)
                                    }
                                    onExited: {
                                        listDelegate.folderDropReady = false
                                        if (root.folderDropTargetUrl === String(listDelegate.url))
                                            root.folderDropTargetUrl = ""
                                    }
                                    onDropped: function(drop) {
                                        const accepted = root.performDrop(drop, listDelegate.url)
                                        listDelegate.folderDropReady = false
                                        if (root.folderDropTargetUrl === String(listDelegate.url))
                                            root.folderDropTargetUrl = ""
                                        if (!accepted)
                                            drop.accepted = false
                                    }
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    enabled: !root.contentScrollbarDragging
                                    acceptedButtons: Qt.LeftButton
                                    onClicked: function(mouse) {
                                        root.selectClicked(listDelegate.index, mouse.modifiers)
                                    }
                                    onDoubleClicked: function(mouse) {
                                        root.selectSingle(listDelegate.index)
                                        directoryModel.openIndex(listDelegate.index)
                                        mouse.accepted = true
                                    }
                                }
                                TapHandler {
                                    acceptedButtons: Qt.RightButton
                                    enabled: !root.contentScrollbarDragging
                                    onTapped: contextPopup.openFor(listDelegate.index, listDelegate)
                                }
                            }

                            Keys.onReturnPressed: {
                                if (root.selectedIndex >= 0)
                                    directoryModel.openIndex(root.selectedIndex)
                            }
                            Keys.onEnterPressed: {
                                if (root.selectedIndex >= 0)
                                    directoryModel.openIndex(root.selectedIndex)
                            }
                        }
                    }

                    MouseArea {
                        id: rubberSelectInput
                        anchors.fill: parent
                        anchors.rightMargin: 12
                        z: 47
                        enabled: !root.contentScrollbarDragging
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        // Do not propagate the synthetic click generated when
                        // a marquee ends over a file. Doing so collapses the
                        // freshly selected group to the file under M1 release.
                        propagateComposedEvents: false
                        preventStealing: true
                        property var activeView: null

                        onPressed: function(mouse) {
                            const view = root.selectionViewAt(mouse.x, mouse.y)
                            if (!view || root.rowAtContentPoint(view, mouse.x, mouse.y) >= 0) {
                                mouse.accepted = false
                                activeView = null
                                return
                            }

                            if (mouse.button === Qt.RightButton) {
                                activeView = null
                                root.clearSelection()
                                backgroundPopup.openAt(mouse.x, mouse.y)
                                mouse.accepted = true
                                return
                            }

                            activeView = view
                            root.beginBackgroundSelection(view, mouse.x, mouse.y, mouse.modifiers)
                            mouse.accepted = true
                        }

                        onPositionChanged: function(mouse) {
                            if (pressed && activeView)
                                root.updateBackgroundSelection(activeView, mouse.x, mouse.y)
                        }

                        onReleased: function(mouse) {
                            if (activeView) {
                                root.endBackgroundSelection()
                                mouse.accepted = true
                            }
                            activeView = null
                        }

                        onCanceled: {
                            root.endBackgroundSelection()
                            activeView = null
                        }

                        onWheel: function(wheel) {
                            wheel.accepted = false
                        }
                    }

                    Rectangle {
                        id: rubberSelection
                        z: 48
                        visible: root.selectionDragActive
                        x: Math.min(root.selectionDragStartX, root.selectionDragCurrentX)
                        y: Math.min(root.selectionDragStartY, root.selectionDragCurrentY)
                        width: Math.abs(root.selectionDragCurrentX - root.selectionDragStartX)
                        height: Math.abs(root.selectionDragCurrentY - root.selectionDragStartY)
                        radius: 8
                        color: root.alpha(root.accent, root.lightMode ? 0.10 : 0.12)
                        border.width: 1
                        border.color: root.alpha(root.accent, 0.48)
                    }

                    DropArea {
                        id: contentDropArea
                        anchors.fill: parent
                        z: 1

                        onEntered: function(drag) {
                            root.acceptDrop(drag, directoryModel.currentUrl)
                        }

                        onDropped: function(drop) {
                            root.performDrop(drop, directoryModel.currentUrl)
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        z: 49
                        visible: contentDropArea.containsDrag && root.folderDropTargetUrl.length === 0
                        color: root.alpha(root.accent, 0.055)
                        border.width: 2
                        border.color: root.alpha(root.accent, 0.30)
                        radius: 18

                        Text {
                            anchors.centerIn: parent
                            text: "Drop files here"
                            color: root.foreground
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                    }

                    BusyIndicator {
                        anchors.centerIn: parent
                        running: directoryModel.loading && grid.count === 0
                        visible: running
                    }

                    Column {
                        anchors.centerIn: parent
                        width: Math.max(180, Math.min(parent.width - 40, 420))
                        spacing: 8
                        visible: !directoryModel.loading
                            && directoryModel.errorString.length === 0
                            && placesController.errorString.length === 0
                            && grid.count === 0

                        Image {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 42
                            height: 42
                            source: root.icon(directoryModel.searchQuery.length > 0 ? "edit-find" : "folder-open")
                            opacity: 0.70
                        }
                        Text {
                            width: parent.width
                            text: directoryModel.searchQuery.length > 0 ? "No results" : "This folder is empty"
                            color: root.foreground
                            font.pixelSize: 16
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: parent.width
                            visible: directoryModel.searchQuery.length > 0
                            text: "Try a different name, type, or path."
                            color: root.alpha(root.muted, 0.76)
                            font.pixelSize: 12
                            horizontalAlignment: Text.AlignHCenter
                            wrapMode: Text.Wrap
                        }
                    }

                    Column {
                        anchors.centerIn: parent
                        width: Math.max(180, Math.min(parent.width - 40, 460))
                        spacing: 10
                        visible: directoryModel.errorString.length > 0 || placesController.errorString.length > 0

                        Image {
                            anchors.horizontalCenter: parent.horizontalCenter
                            width: 38
                            height: 38
                            source: root.icon("dialog-error")
                            opacity: 0.74
                        }
                        Text {
                            width: parent.width
                            text: "Couldn’t open this location"
                            color: root.foreground
                            font.pixelSize: root.width < 480 ? 15 : 18
                            font.weight: Font.DemiBold
                            horizontalAlignment: Text.AlignHCenter
                        }
                        Text {
                            width: parent.width
                            text: placesController.errorString.length > 0 ? placesController.errorString : directoryModel.errorString
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
                Layout.preferredHeight: root.height < 320 ? 32 : 40
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
                    anchors.leftMargin: root.tinyToolbar ? 10 : 20
                    anchors.rightMargin: root.tinyToolbar ? 10 : 20

                    Text {
                        text: root.selectedCount > 0
                            ? root.selectedCount + " selected · " + grid.count + (grid.count === 1 ? " item" : " items")
                            : grid.count + (grid.count === 1 ? " item" : " items")
                        color: root.alpha(root.muted, root.selectedCount > 0 ? 0.92 : 0.76)
                        font.pixelSize: 11
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        visible: directoryModel.operationMessage.length > 0 && root.width >= 520
                        text: directoryModel.operationMessage
                        color: root.alpha(root.foreground, 0.72)
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }

                    Text {
                        visible: directoryModel.operationBusy && directoryModel.operationProgress >= 0
                        text: directoryModel.operationProgress + "%"
                        color: root.alpha(root.foreground, 0.74)
                        font.pixelSize: 11
                    }

                    BusyIndicator {
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18
                        running: directoryModel.operationBusy && directoryModel.operationProgress < 0
                        visible: running
                    }

                    Rectangle {
                        visible: directoryModel.canCancelOperation
                        Layout.preferredWidth: 58
                        Layout.preferredHeight: 26
                        radius: 9
                        color: cancelOperationHover.hovered ? root.hoverFill : root.alpha(root.foreground, 0.035)
                        border.width: 1
                        border.color: root.alpha(root.foreground, 0.08)

                        Text {
                            anchors.centerIn: parent
                            text: "Cancel"
                            color: root.foreground
                            font.pixelSize: 11
                        }
                        HoverHandler { id: cancelOperationHover }
                        TapHandler { onTapped: directoryModel.cancelOperation() }
                    }

                    Text {
                        visible: directoryModel.showHidden && root.width >= 600
                        text: "Hidden visible"
                        color: root.alpha(root.accent, 0.82)
                        font.pixelSize: 11
                    }
                }
            }
        }
    }

    WindowResizeHandle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 7
        edges: Qt.LeftEdge
        resizeCursor: Qt.SizeHorCursor
    }
    WindowResizeHandle {
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 7
        edges: Qt.RightEdge
        resizeCursor: Qt.SizeHorCursor
    }
    WindowResizeHandle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 7
        edges: Qt.TopEdge
        resizeCursor: Qt.SizeVerCursor
    }
    WindowResizeHandle {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 7
        edges: Qt.BottomEdge
        resizeCursor: Qt.SizeVerCursor
    }

    WindowResizeHandle {
        anchors.left: parent.left
        anchors.top: parent.top
        width: 13
        height: 13
        edges: Qt.LeftEdge | Qt.TopEdge
        resizeCursor: Qt.SizeFDiagCursor
    }
    WindowResizeHandle {
        anchors.right: parent.right
        anchors.top: parent.top
        width: 13
        height: 13
        edges: Qt.RightEdge | Qt.TopEdge
        resizeCursor: Qt.SizeBDiagCursor
    }
    WindowResizeHandle {
        anchors.left: parent.left
        anchors.bottom: parent.bottom
        width: 13
        height: 13
        edges: Qt.LeftEdge | Qt.BottomEdge
        resizeCursor: Qt.SizeBDiagCursor
    }
    WindowResizeHandle {
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: 13
        height: 13
        edges: Qt.RightEdge | Qt.BottomEdge
        resizeCursor: Qt.SizeFDiagCursor
    }
}
