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

    property string viewMode: "grid"
    property bool searchVisible: false
    property int selectedIndex: -1
    property real sidebarWidth: 228

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

    function showSearch() {
        searchVisible = true
        Qt.callLater(function() {
            searchField.forceActiveFocus()
            searchField.selectAll()
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

    Shortcut { sequence: "Alt+Left"; onActivated: directoryModel.goBack() }
    Shortcut { sequence: "Alt+Right"; onActivated: directoryModel.goForward() }
    Shortcut { sequence: "Alt+Up"; onActivated: directoryModel.goUp() }
    Shortcut { sequence: "Ctrl+L"; onActivated: { pathField.forceActiveFocus(); pathField.selectAll() } }
    Shortcut { sequence: "Ctrl+F"; onActivated: root.showSearch() }
    Shortcut { sequence: "Ctrl+H"; onActivated: directoryModel.showHidden = !directoryModel.showHidden }
    Shortcut { sequence: "Ctrl+Shift+N"; onActivated: namePopup.beginNewFolder() }
    Shortcut { sequence: "F5"; onActivated: directoryModel.reload() }
    Shortcut { sequence: "F2"; enabled: root.selectedIndex >= 0; onActivated: namePopup.beginRename(root.selectedIndex) }
    Shortcut { sequence: "Delete"; enabled: root.selectedIndex >= 0; onActivated: directoryModel.trashIndex(root.selectedIndex) }
    Shortcut { sequence: "Ctrl+C"; enabled: root.selectedIndex >= 0; onActivated: directoryModel.copyIndex(root.selectedIndex, false) }
    Shortcut { sequence: "Ctrl+X"; enabled: root.selectedIndex >= 0; onActivated: directoryModel.copyIndex(root.selectedIndex, true) }
    Shortcut { sequence: "Ctrl+V"; enabled: directoryModel.canPaste; onActivated: directoryModel.paste() }

    Connections {
        target: directoryModel
        function onCurrentUrlChanged() {
            root.selectedIndex = -1
            if (!pathField.activeFocus)
                pathField.text = directoryModel.displayPath
        }
        function onSearchQueryChanged() {
            if (!searchField.activeFocus)
                searchField.text = directoryModel.searchQuery
        }
    }

    Popup {
        id: morePopup
        parent: Overlay.overlay
        padding: 8
        width: 242
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
                onTriggered: { morePopup.close(); namePopup.beginNewFolder() }
            }
            MenuAction {
                label: "Paste"
                iconName: "edit-paste"
                enabledState: directoryModel.canPaste
                onTriggered: { morePopup.close(); directoryModel.paste() }
            }
            Rectangle { width: 226; height: 1; color: root.divider }
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
            Rectangle { width: 226; height: 1; color: root.divider }
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
        width: 242
        modal: false
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        property int targetIndex: -1

        function openFor(index, item) {
            targetIndex = index
            root.selectedIndex = index
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
                onTriggered: { const row = contextPopup.targetIndex; contextPopup.close(); namePopup.beginRename(row) }
            }
            Rectangle { width: 226; height: 1; color: root.divider }
            MenuAction {
                label: "Copy"
                iconName: "edit-copy"
                onTriggered: { contextPopup.close(); directoryModel.copyIndex(contextPopup.targetIndex, false) }
            }
            MenuAction {
                label: "Cut"
                iconName: "edit-cut"
                onTriggered: { contextPopup.close(); directoryModel.copyIndex(contextPopup.targetIndex, true) }
            }
            MenuAction {
                label: "Paste Here"
                iconName: "edit-paste"
                enabledState: directoryModel.canPaste
                onTriggered: { contextPopup.close(); directoryModel.paste() }
            }
            Rectangle { width: 226; height: 1; color: root.divider }
            MenuAction {
                label: "Move to Trash"
                iconName: "user-trash"
                destructive: true
                onTriggered: { contextPopup.close(); directoryModel.trashIndex(contextPopup.targetIndex) }
            }
        }
    }

    Popup {
        id: namePopup
        parent: Overlay.overlay
        modal: true
        focus: true
        padding: 18
        width: 380
        height: 178
        anchors.centerIn: Overlay.overlay
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        property string mode: "new"
        property int targetIndex: -1

        function beginNewFolder() {
            mode = "new"
            targetIndex = -1
            nameField.text = "New Folder"
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
            if (nameField.text.trim().length === 0)
                return
            if (mode === "new")
                directoryModel.createFolder(nameField.text)
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
                text: namePopup.mode === "new" ? "New Folder" : "Rename"
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
                    label: namePopup.mode === "new" ? "Create" : "Rename"
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
                Layout.preferredHeight: 72
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
                    anchors.leftMargin: 16
                    anchors.rightMargin: 16
                    spacing: 6

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
                        onTriggered: directoryModel.goUp()
                    }
                    IconButton {
                        glyph: "home"
                        tooltip: "Home"
                        onTriggered: directoryModel.goHome()
                    }

                    Rectangle {
                        Layout.leftMargin: 7
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
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
                        }

                        TextField {
                            id: pathField
                            anchors.fill: parent
                            anchors.leftMargin: 38
                            anchors.rightMargin: 12
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
                Layout.preferredHeight: root.searchVisible ? 54 : 0
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
                    width: Math.min(parent.width - 36, 620)
                    height: 38
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
                            text = ""
                            directoryModel.searchQuery = ""
                            root.searchVisible = false
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                Rectangle {
                    Layout.preferredWidth: root.sidebarWidth
                    Layout.fillHeight: true
                    color: root.sidebarFill

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
                            property bool deviceActionAvailable: placesController.canEject(index) || placesController.canTeardown(index)

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
                        anchors.fill: parent
                        anchors.margins: 18
                        cellWidth: 138
                        cellHeight: 124
                        clip: true
                        visible: root.viewMode === "grid"
                        model: directoryModel
                        boundsBehavior: Flickable.StopAtBounds
                        keyNavigationEnabled: true
                        focus: visible

                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

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
                            property bool selected: root.selectedIndex === index

                            Rectangle {
                                anchors.fill: parent
                                anchors.margins: 3
                                radius: 18
                                color: fileDelegate.selected
                                    ? root.selectedFill
                                    : fileHover.hovered ? root.hoverFill : "transparent"
                                border.width: fileDelegate.selected ? 1 : 0
                                border.color: root.selectedRim
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
                                    width: 70
                                    height: 70

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
                                        width: 62
                                        height: 62
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
                                    maximumLineCount: 2
                                    wrapMode: Text.Wrap
                                    elide: Text.ElideRight
                                }
                            }

                            HoverHandler { id: fileHover }
                            TapHandler {
                                acceptedButtons: Qt.LeftButton
                                onTapped: root.selectedIndex = fileDelegate.index
                                onDoubleTapped: directoryModel.openIndex(fileDelegate.index)
                            }
                            TapHandler {
                                acceptedButtons: Qt.RightButton
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
                        anchors.fill: parent
                        anchors.margins: 16
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
                                Text { Layout.preferredWidth: 100; text: "Size"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
                                Text { Layout.preferredWidth: 150; text: "Type"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
                                Text { Layout.preferredWidth: 180; text: "Modified"; color: root.alpha(root.muted, 0.72); font.pixelSize: 11 }
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

                            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                            delegate: Item {
                                id: listDelegate
                                required property int index
                                required property string name
                                required property string iconName
                                required property string sizeText
                                required property string mimeComment
                                required property string modifiedText
                                required property url previewUrl

                                width: listView.width
                                height: 44
                                property bool selected: root.selectedIndex === index

                                Rectangle {
                                    anchors.fill: parent
                                    radius: 11
                                    color: listDelegate.selected
                                        ? root.selectedFill
                                        : listHover.hovered ? root.hoverFill : "transparent"
                                    border.width: listDelegate.selected ? 1 : 0
                                    border.color: root.selectedRim
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

                                    Text { Layout.preferredWidth: 100; text: listDelegate.sizeText; color: root.alpha(root.muted, 0.82); font.pixelSize: 11; elide: Text.ElideRight }
                                    Text { Layout.preferredWidth: 150; text: listDelegate.mimeComment; color: root.alpha(root.muted, 0.82); font.pixelSize: 11; elide: Text.ElideRight }
                                    Text { Layout.preferredWidth: 180; text: listDelegate.modifiedText; color: root.alpha(root.muted, 0.82); font.pixelSize: 11; elide: Text.ElideRight }
                                }

                                HoverHandler { id: listHover }
                                TapHandler {
                                    acceptedButtons: Qt.LeftButton
                                    onTapped: root.selectedIndex = listDelegate.index
                                    onDoubleTapped: directoryModel.openIndex(listDelegate.index)
                                }
                                TapHandler {
                                    acceptedButtons: Qt.RightButton
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

                    BusyIndicator {
                        anchors.centerIn: parent
                        running: directoryModel.loading && grid.count === 0
                        visible: running
                    }

                    Column {
                        anchors.centerIn: parent
                        width: Math.min(parent.width - 80, 460)
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
                            font.pixelSize: 18
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
                Layout.preferredHeight: 40
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
                    anchors.leftMargin: 20
                    anchors.rightMargin: 20

                    Text {
                        text: grid.count + (grid.count === 1 ? " item" : " items")
                        color: root.alpha(root.muted, 0.76)
                        font.pixelSize: 11
                    }

                    Item { Layout.fillWidth: true }

                    Text {
                        visible: directoryModel.operationMessage.length > 0
                        text: directoryModel.operationMessage
                        color: root.alpha(root.foreground, 0.72)
                        font.pixelSize: 11
                        elide: Text.ElideRight
                    }

                    BusyIndicator {
                        Layout.preferredWidth: 18
                        Layout.preferredHeight: 18
                        running: directoryModel.operationBusy
                        visible: running
                    }

                    Text {
                        visible: directoryModel.showHidden
                        text: "Hidden visible"
                        color: root.alpha(root.accent, 0.82)
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
