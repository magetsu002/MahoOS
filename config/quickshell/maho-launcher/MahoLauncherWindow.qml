import QtQuick
import QtQuick.Layouts
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland
import Quickshell.Widgets

PanelWindow {
    id: root

    color: "transparent"
    implicitWidth: Math.min(640, Math.max(420, (screen ? screen.width : 672) - 32))
    implicitHeight: Math.min(780, Math.max(560, (screen ? screen.height : 812) - 32))
    exclusiveZone: 0
    exclusionMode: ExclusionMode.Ignore
    aboveWindows: true
    focusable: true
    WlrLayershell.namespace: "maho-launcher"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

    LauncherTheme { id: theme }

    property int currentMode: 0
    property int maximumResults: 48

    function descriptionFor(entry) {
        if (entry.genericName && entry.genericName.trim().length > 0)
            return entry.genericName.trim()
        if (entry.comment && entry.comment.trim().length > 0)
            return entry.comment.trim()
        if (entry.categories && entry.categories.length > 0)
            return entry.categories[0].replace(/;/g, "")
        return "Application"
    }

    function searchableText(entry) {
        const keywords = entry.keywords ? entry.keywords.join(" ") : ""
        const categories = entry.categories ? entry.categories.join(" ") : ""
        return (entry.name + " " + entry.genericName + " " + entry.comment
            + " " + keywords + " " + categories).toLowerCase()
    }

    function fuzzyScore(entry, rawQuery) {
        const query = rawQuery.trim().toLowerCase()
        if (query.length === 0)
            return 0

        const name = entry.name.toLowerCase()
        const haystack = searchableText(entry)
        if (name === query)
            return 10000
        if (name.startsWith(query))
            return 7000 - name.length
        if (name.indexOf(query) >= 0)
            return 5000 - name.indexOf(query)
        if (haystack.indexOf(query) >= 0)
            return 3000 - haystack.indexOf(query)

        let queryIndex = 0
        let gapPenalty = 0
        let previousMatch = -1
        for (let index = 0; index < haystack.length && queryIndex < query.length; ++index) {
            if (haystack[index] !== query[queryIndex])
                continue
            if (previousMatch >= 0)
                gapPenalty += index - previousMatch - 1
            previousMatch = index
            queryIndex += 1
        }

        if (queryIndex !== query.length)
            return -1
        return 1000 - gapPenalty - Math.max(0, haystack.length - query.length) * 0.01
    }

    function refilter() {
        const query = searchInput.text
        const values = DesktopEntries.applications.values || []
        let matches = []

        for (let index = 0; index < values.length; ++index) {
            const entry = values[index]
            if (!entry || entry.noDisplay || !entry.name)
                continue
            const score = fuzzyScore(entry, query)
            if (score >= 0)
                matches.push({ "entry": entry, "score": score })
        }

        matches.sort(function(first, second) {
            if (first.score !== second.score)
                return second.score - first.score
            return first.entry.name.localeCompare(second.entry.name)
        })

        const filtered = []
        for (let result = 0; result < Math.min(matches.length, maximumResults); ++result)
            filtered.push(matches[result].entry)
        appModel.values = filtered
        resultList.currentIndex = filtered.length > 0 ? 0 : -1
        if (resultList.currentIndex >= 0) {
            resultList.positionViewAtIndex(0, ListView.Beginning)
            Qt.callLater(function() { resultList.positionViewAtBeginning() })
        }
    }

    function moveSelection(delta) {
        if (currentMode !== 0 || resultList.count === 0)
            return
        const next = Math.max(0, Math.min(resultList.count - 1, resultList.currentIndex + delta))
        resultList.currentIndex = next
        resultList.positionViewAtIndex(next, ListView.Contain)
    }

    function launchSelected() {
        if (currentMode !== 0 || resultList.currentIndex < 0)
            return
        const row = resultList.currentItem
        const entry = row ? row.modelData : null
        if (!entry)
            return

        // DesktopEntry.execute() tokenizes and launches the desktop entry. Raw
        // Exec text is never passed to a shell or evaluated by this launcher.
        entry.execute()
        closeAfterLaunch.restart()
    }

    function closeLauncher() {
        Qt.quit()
    }

    ScriptModel { id: appModel }

    Connections {
        target: DesktopEntries.applications
        function onValuesChanged() { root.refilter() }
    }

    Timer {
        id: closeAfterLaunch
        interval: 80
        onTriggered: root.closeLauncher()
    }

    Component.onCompleted: {
        refilter()
        Qt.callLater(function() { searchInput.forceActiveFocus() })
    }

    Rectangle {
        id: panelShadow
        objectName: "MaterialPanelShadow"
        x: 9
        y: materialPanel.y + 10
        width: parent.width - 18
        height: materialPanel.height - 2
        radius: materialPanel.radius + 2
        color: theme.shadow
        opacity: 0.58
    }

    Rectangle {
        id: materialPanel
        objectName: "MaterialPanel"
        x: 1
        y: 116
        width: parent.width - 2
        height: parent.height - y - 1
        radius: 21
        color: theme.panelTint
        border.width: 1
        border.color: theme.panelBorder
        clip: true

        ColumnLayout {
            anchors.fill: parent
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            anchors.topMargin: 8
            spacing: 0

            Item {
                Layout.fillWidth: true
                Layout.preferredHeight: 54

                Row {
                    anchors.centerIn: parent
                    spacing: 12

                    TintedIcon {
                        width: 34
                        height: 34
                        anchors.verticalCenter: parent.verticalCenter
                        source: "assets/maho-logo.png"
                        tint: theme.primary
                    }

                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 7

                        Text {
                            text: "Maho"
                            color: theme.foreground
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 24
                            font.weight: Font.DemiBold
                        }

                        Text {
                            text: "Launcher"
                            color: theme.muted
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 24
                            font.weight: Font.Normal
                        }
                    }
                }
            }

            Rectangle {
                id: searchField
                objectName: "SearchField"
                Layout.fillWidth: true
                Layout.preferredHeight: 58
                Layout.topMargin: 6
                radius: 13
                color: theme.searchTint
                border.width: searchInput.activeFocus ? 1.5 : 1
                border.color: searchInput.activeFocus ? theme.focusRing : theme.searchBorder

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 17
                    anchors.rightMargin: 13
                    spacing: 13

                    TintedIcon {
                        Layout.preferredWidth: 24
                        Layout.preferredHeight: 24
                        Layout.alignment: Qt.AlignVCenter
                        source: "assets/icons/search.png"
                        tint: theme.muted
                    }

                    Item {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            visible: searchInput.text.length === 0
                            text: "Search apps, files, commands..."
                            color: theme.alpha(theme.muted, 0.72)
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 16
                        }

                        TextInput {
                            id: searchInput
                            objectName: "LauncherSearchInput"
                            anchors.fill: parent
                            verticalAlignment: TextInput.AlignVCenter
                            color: theme.foreground
                            selectionColor: theme.selectedMode
                            selectedTextColor: theme.foreground
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 16
                            clip: true
                            focus: true
                            activeFocusOnTab: true
                            onTextChanged: root.refilter()

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
                                    root.launchSelected()
                                    event.accepted = true
                                }
                            }
                        }
                    }

                    Rectangle {
                        Layout.preferredWidth: 34
                        Layout.preferredHeight: 34
                        Layout.alignment: Qt.AlignVCenter
                        radius: 7
                        color: theme.keyChip
                        border.width: 1
                        border.color: theme.keyBorder

                        Text {
                            anchors.centerIn: parent
                            text: "/"
                            color: theme.muted
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                        }
                    }
                }
            }

            Item {
                id: modeTabs
                objectName: "ModeTabs"
                Layout.fillWidth: true
                Layout.preferredHeight: 75
                Layout.topMargin: 8

                RowLayout {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 10
                    height: 54
                    spacing: 8

                    Repeater {
                        model: [
                            { "label": "Apps", "icon": "assets/icons/apps.png" },
                            { "label": "Files", "icon": "assets/icons/files.png" },
                            { "label": "Commands", "icon": "assets/icons/commands.png" }
                        ]

                        Rectangle {
                            required property int index
                            required property var modelData

                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            radius: 12
                            color: root.currentMode === index ? theme.selectedMode : "transparent"
                            border.width: root.currentMode === index ? 1 : 0
                            border.color: root.currentMode === index
                                ? theme.alpha(theme.primary, 0.20) : "transparent"

                            Row {
                                anchors.centerIn: parent
                                spacing: 10

                                TintedIcon {
                                    width: 21
                                    height: 21
                                    anchors.verticalCenter: parent.verticalCenter
                                    source: modelData.icon
                                    tint: root.currentMode === index ? theme.foreground : theme.muted
                                }

                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: modelData.label
                                    color: root.currentMode === index ? theme.foreground : theme.muted
                                    font.family: "Inter, Noto Sans, sans-serif"
                                    font.pixelSize: 15
                                    font.weight: root.currentMode === index ? Font.DemiBold : Font.Medium
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.currentMode = index
                                    searchInput.forceActiveFocus()
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: theme.divider
                }
            }

            Item {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 250
                Layout.topMargin: 10

                ListView {
                    id: resultList
                    objectName: "BoundedScrollableResults"
                    anchors.fill: parent
                    visible: root.currentMode === 0
                    clip: true
                    spacing: 4
                    model: appModel
                    currentIndex: count > 0 ? 0 : -1
                    boundsBehavior: Flickable.StopAtBounds
                    keyNavigationEnabled: false
                    highlightFollowsCurrentItem: true
                    highlightMoveDuration: 115
                    highlightResizeDuration: 90

                    highlight: Rectangle {
                        objectName: "SelectedResultState"
                        radius: 12
                        color: theme.selectedResult
                        border.width: 1
                        border.color: theme.selectedOutline
                    }

                    delegate: Item {
                        id: resultRow
                        required property int index
                        required property var modelData
                        width: ListView.view.width
                        height: 60

                        Item {
                            id: appIconContainer
                            property bool themeIconAvailable: modelData.icon
                                && Quickshell.hasThemeIcon(modelData.icon)
                            anchors.left: parent.left
                            anchors.leftMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            width: 38
                            height: 38

                            Image {
                                anchors.fill: parent
                                source: "assets/icons/app-fallback.png"
                                fillMode: Image.PreserveAspectFit
                                mipmap: true
                                visible: !appIconContainer.themeIconAvailable
                                    || appIcon.status !== Image.Ready
                            }

                            IconImage {
                                id: appIcon
                                anchors.fill: parent
                                source: appIconContainer.themeIconAvailable
                                    ? Quickshell.iconPath(modelData.icon) : ""
                                mipmap: true
                                visible: status === Image.Ready
                            }
                        }

                        Column {
                            anchors.left: appIconContainer.right
                            anchors.leftMargin: 15
                            anchors.right: shortcutNumber.left
                            anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 4

                            Text {
                                width: parent.width
                                text: modelData.name
                                color: theme.foreground
                                elide: Text.ElideRight
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 15
                                font.weight: Font.DemiBold
                            }

                            Text {
                                width: parent.width
                                text: root.descriptionFor(modelData)
                                color: theme.alpha(theme.muted, 0.82)
                                elide: Text.ElideRight
                                font.family: "Inter, Noto Sans, sans-serif"
                                font.pixelSize: 12
                            }
                        }

                        Text {
                            id: shortcutNumber
                            anchors.right: parent.right
                            anchors.rightMargin: 16
                            anchors.verticalCenter: parent.verticalCenter
                            width: 18
                            horizontalAlignment: Text.AlignHCenter
                            text: index < 9 ? String(index + 1) : ""
                            color: theme.alpha(theme.muted, 0.82)
                            font.family: "Inter, Noto Sans, sans-serif"
                            font.pixelSize: 13
                            font.weight: Font.Medium
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onEntered: resultList.currentIndex = index
                            onClicked: {
                                resultList.currentIndex = index
                                root.launchSelected()
                            }
                        }
                    }

                    Text {
                        anchors.centerIn: parent
                        visible: resultList.count === 0
                        text: searchInput.text.length > 0 ? "No applications found" : "No applications available"
                        color: theme.muted
                        font.family: "Inter, Noto Sans, sans-serif"
                        font.pixelSize: 15
                    }
                }

                Column {
                    anchors.centerIn: parent
                    visible: root.currentMode !== 0
                    spacing: 8

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.currentMode === 1 ? "File search arrives in L2" : "Command mode arrives in L2"
                        color: theme.foreground
                        font.family: "Inter, Noto Sans, sans-serif"
                        font.pixelSize: 15
                        font.weight: Font.DemiBold
                    }

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: root.currentMode === 1
                            ? "Apps mode is ready now. Files stay safely bounded for L1."
                            : "Arbitrary shell execution is intentionally disabled in L1."
                        color: theme.muted
                        font.family: "Inter, Noto Sans, sans-serif"
                        font.pixelSize: 12
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 1
                color: theme.divider
            }

            RowLayout {
                objectName: "LauncherFooter"
                Layout.fillWidth: true
                Layout.preferredHeight: 58
                spacing: 8

                KeyHint {
                    theme: theme
                    keyText: "↵ Enter"
                    label: "to launch"
                }

                Item { Layout.fillWidth: true }

                KeyHint {
                    theme: theme
                    keyText: "ESC"
                    label: "to close"
                }

                Item { Layout.fillWidth: true }

                KeyHint {
                    theme: theme
                    keyText: "↑  ↓"
                    label: "to navigate"
                }
            }
        }
    }

    Item {
        id: mascotLayer
        objectName: "MascotLayer"
        x: 10
        y: 8
        width: 230
        height: 129
        enabled: false

        Image {
            id: mascotGlowSource
            anchors.fill: parent
            source: "assets/maho-mascot.png"
            fillMode: Image.PreserveAspectFit
            opacity: 0.62
            layer.enabled: true
            layer.effect: MultiEffect {
                blurEnabled: true
                blur: 0.68
                blurMax: 34
                colorization: 0.78
                colorizationColor: theme.mascotGlow
            }
        }

        Image {
            id: mascotArtwork
            objectName: "MascotArtwork"
            anchors.fill: parent
            source: "assets/maho-mascot.png"
            fillMode: Image.PreserveAspectFit
            mipmap: true
        }
    }
}
