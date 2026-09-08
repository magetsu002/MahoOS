import QtQuick

Item {
    id: root

    required property var theme
    required property var clipboardState
    property bool shown: false
    property string query: ""
    property var filteredItems: []
    signal closeRequested()

    width: 510
    height: 590
    focus: shown

    // The whole sheet moves as one object. Keeping the content attached to the
    // glass avoids the layered/staggered feeling of the previous pass.
    property real revealProgress: shown ? 1 : 0

    opacity: Math.min(1, revealProgress * 1.8)
    scale: 0.988 + (revealProgress * 0.012)
    transformOrigin: Item.Bottom

    transform: Translate {
        y: (1 - root.revealProgress) * 214
    }

    Behavior on revealProgress {
        NumberAnimation {
            duration: root.shown ? 350 : 215
            easing.type: root.shown ? Easing.OutExpo : Easing.InCubic
        }
    }

    readonly property color textPrimary: theme.foreground
    readonly property color textSecondary: theme.alpha(theme.muted, 0.78)
    readonly property color accent: stableAccent(theme.primary)

    // Use the same material recipe as the Bluetooth side of Maho Link. The
    // compositor supplies the wallpaper blur; QML only provides the neutral
    // translucent pane, quiet palette wash, and edge reflections.
    readonly property color neutralGlass: mix(theme.surfaceHigh, theme.background, 0.54)
    readonly property color tintedGlass: mix(neutralGlass, accent, 0.018)
    readonly property color shellFill: theme.alpha(neutralGlass, 0.72)
    readonly property color shellStroke: theme.alpha(theme.foreground, 0.105)
    readonly property color shellHighlight: theme.alpha(theme.foreground, 0.115)
    readonly property color searchFill: theme.alpha(mix(theme.surfaceHigh, theme.background, 0.44), 0.31)

    function mix(a, b, amount) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            a.r * (1 - t) + b.r * t,
            a.g * (1 - t) + b.g * t,
            a.b * (1 - t) + b.b * t,
            a.a * (1 - t) + b.a * t
        )
    }

    function stableAccent(source) {
        const saturation = source.hsvSaturation
        if (saturation < 0.08)
            return mix(theme.foreground, theme.surfaceHigh, 0.38)
        const hue = source.hsvHue < 0 ? 0 : source.hsvHue
        return Qt.hsva(
            hue,
            Math.max(0.20, Math.min(0.62, saturation)),
            Math.max(0.62, Math.min(0.88, source.hsvValue)),
            1
        )
    }

    function resetSelectionToBeginning() {
        Qt.callLater(function() {
            if (root.filteredItems.length === 0) {
                list.currentIndex = -1
                return
            }
            list.currentIndex = 0
            list.positionViewAtBeginning()
            list.positionViewAtIndex(0, ListView.Beginning)
        })
    }

    function rebuildFilter() {
        const needle = String(query || "").trim().toLowerCase()
        const source = root.clipboardState.items || []
        if (needle === "") {
            filteredItems = source.slice(0)
        } else {
            const result = []
            for (let i = 0; i < source.length; ++i) {
                if (String(source[i].search || "").indexOf(needle) !== -1)
                    result.push(source[i])
            }
            filteredItems = result
        }
        resetSelectionToBeginning()
    }

    function moveSelection(delta) {
        if (filteredItems.length === 0)
            return
        const current = list.currentIndex < 0 ? 0 : list.currentIndex
        list.currentIndex = Math.max(0, Math.min(filteredItems.length - 1, current + delta))
        list.positionViewAtIndex(list.currentIndex, ListView.Contain)
    }

    function activateSelection() {
        if (list.currentIndex < 0 || list.currentIndex >= filteredItems.length)
            return
        root.clipboardState.selectItem(filteredItems[list.currentIndex].id)
    }

    onQueryChanged: rebuildFilter()

    Connections {
        target: root.clipboardState
        function onItemsChanged() { root.rebuildFilter() }
    }

    // One clipped shell owns the complete perimeter, matching Maho Link. The
    // lower 24 px remain below the logical monitor edge to preserve the target
    // bottom-menu silhouette without any fake glow/vignette layer.
    Rectangle {
        id: shellMaterial
        z: -1
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.height + 24
        radius: 28
        antialiasing: true
        color: root.shellFill
        border.width: 1
        border.color: root.shellStroke
        clip: true

        // QML's clip is rectangular, not radius-aware. Give the material wash
        // the same rounded silhouette instead of letting a full rectangular
        // gradient paint tiny square corners over the shell radius.
        Rectangle {
            anchors.fill: parent
            radius: shellMaterial.radius
            antialiasing: true
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.00; color: theme.alpha(theme.foreground, 0.032) }
                GradientStop { position: 0.20; color: theme.alpha(root.accent, 0.018) }
                GradientStop { position: 0.60; color: "transparent" }
                GradientStop { position: 1.00; color: theme.alpha(root.accent, 0.035) }
            }
        }

        // Keep edge reflections safely inside the tangent points of the rounded
        // shell so no one-pixel straight segment can poke into a curved corner.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 34
            anchors.rightMargin: 34
            anchors.top: parent.top
            height: 1
            color: root.shellHighlight
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 32
            anchors.rightMargin: 32
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 23
            height: 1
            color: theme.alpha(root.accent, 0.055)
        }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        onClicked: function(mouse) { mouse.accepted = true }
    }

    Item {
        id: header
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 23
        anchors.rightMargin: 20
        anchors.topMargin: 20
        height: 40

        Rectangle {
            id: clipboardGlyph
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: 34
            height: 34
            radius: 10
            color: theme.alpha(root.mix(root.textSecondary, root.accent, 0.14), 0.065)
            border.width: 1
            border.color: theme.alpha(theme.foreground, 0.030)

            Rectangle {
                anchors.centerIn: parent
                width: 14
                height: 17
                radius: 3
                color: "transparent"
                border.width: 1.2
                border.color: theme.alpha(root.mix(root.textPrimary, root.accent, 0.18), 0.90)

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.top: parent.top
                    anchors.topMargin: -2
                    width: 7
                    height: 4
                    radius: 2
                    color: root.tintedGlass
                    border.width: 1
                    border.color: theme.alpha(root.mix(root.textPrimary, root.accent, 0.18), 0.90)
                }
            }
        }

        Text {
            anchors.left: clipboardGlyph.right
            anchors.leftMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            text: "Clipboard"
            color: root.textPrimary
            font.family: "Inter"
            font.pixelSize: 18
            font.weight: Font.Medium
        }

        Rectangle {
            id: clearButton
            anchors.right: closeButton.left
            anchors.rightMargin: 5
            anchors.verticalCenter: parent.verticalCenter
            width: 50
            height: 30
            radius: 10
            color: clearHover.containsMouse ? theme.alpha(root.textSecondary, 0.038) : "transparent"
            opacity: root.clipboardState.mutating ? 0.45 : 1

            Text {
                anchors.centerIn: parent
                text: "Clear"
                color: theme.alpha(root.textSecondary, clearHover.containsMouse ? 0.96 : 0.76)
                font.family: "Inter"
                font.pixelSize: 11
                font.weight: Font.Medium
            }

            MouseArea {
                id: clearHover
                anchors.fill: parent
                enabled: !root.clipboardState.mutating
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.clipboardState.clearUnpinned()
            }
        }

        Rectangle {
            id: closeButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            width: 30
            height: 30
            radius: 10
            color: closeHover.containsMouse ? theme.alpha(root.textSecondary, 0.038) : "transparent"
            Behavior on color { ColorAnimation { duration: 90 } }

            Text {
                anchors.centerIn: parent
                text: "×"
                color: theme.alpha(root.textSecondary, closeHover.containsMouse ? 0.96 : 0.80)
                font.family: "Inter"
                font.pixelSize: 20
                font.weight: Font.Light
            }

            MouseArea {
                id: closeHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.closeRequested()
            }
        }
    }

    Rectangle {
        id: searchBox
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.leftMargin: 22
        anchors.rightMargin: 22
        anchors.topMargin: 13
        height: 48
        radius: 16
        antialiasing: true
        color: searchInput.activeFocus
            ? theme.alpha(root.mix(root.searchFill, root.accent, 0.07), 0.40)
            : root.searchFill
        border.width: 1
        border.color: searchInput.activeFocus
            ? theme.alpha(root.accent, 0.080)
            : theme.alpha(theme.foreground, 0.050)
        Behavior on color { ColorAnimation { duration: 110 } }
        Behavior on border.color { ColorAnimation { duration: 110 } }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 18
            anchors.rightMargin: 18
            height: 1
            color: theme.alpha(theme.foreground, 0.025)
        }

        Item {
            id: searchGlyph
            anchors.left: parent.left
            anchors.leftMargin: 17
            anchors.verticalCenter: parent.verticalCenter
            width: 19
            height: 19

            Rectangle {
                x: 1
                y: 1
                width: 11
                height: 11
                radius: 6
                color: "transparent"
                border.width: 1.4
                border.color: theme.alpha(root.textPrimary, 0.80)
            }

            Rectangle {
                x: 11
                y: 12
                width: 7
                height: 1.4
                radius: 1
                rotation: 45
                transformOrigin: Item.Left
                color: theme.alpha(root.textPrimary, 0.80)
            }
        }

        TextInput {
            id: searchInput
            anchors.left: searchGlyph.right
            anchors.leftMargin: 13
            anchors.right: parent.right
            anchors.rightMargin: 17
            anchors.verticalCenter: parent.verticalCenter
            color: root.textPrimary
            selectionColor: theme.alpha(root.accent, 0.26)
            selectedTextColor: root.textPrimary
            font.family: "Inter"
            font.pixelSize: 13
            clip: true
            focus: root.shown

            Text {
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                visible: searchInput.text.length === 0
                text: "Type to filter"
                color: theme.alpha(root.textSecondary, 0.66)
                font: searchInput.font
            }

            onTextChanged: root.query = text

            Keys.onPressed: function(event) {
                if (event.key === Qt.Key_Down) {
                    root.moveSelection(1)
                    event.accepted = true
                } else if (event.key === Qt.Key_Up) {
                    root.moveSelection(-1)
                    event.accepted = true
                } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    root.activateSelection()
                    event.accepted = true
                } else if (event.key === Qt.Key_Escape) {
                    root.closeRequested()
                    event.accepted = true
                }
            }
        }
    }

    Item {
        id: listSurface
        z: 2
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: searchBox.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 17
        anchors.rightMargin: 17
        anchors.topMargin: 13
        anchors.bottomMargin: 16
        clip: true

        ListView {
            id: list
            property var clipboardState: root.clipboardState
            anchors.fill: parent
            model: root.filteredItems
            currentIndex: root.filteredItems.length > 0 ? 0 : -1
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            spacing: 0

            delegate: Item {
                id: row
                required property var modelData
                required property int index
                width: ListView.view.width
                height: 70
                readonly property bool selected: ListView.isCurrentItem
                readonly property bool revealPin: rowHover.containsMouse || pinHover.containsMouse

                Rectangle {
                    anchors.fill: parent
                    anchors.leftMargin: 1
                    anchors.rightMargin: 1
                    anchors.topMargin: 2
                    anchors.bottomMargin: 2
                    radius: 15
                    color: row.selected
                        ? theme.alpha(root.mix(root.accent, theme.surfaceHigh, 0.32), 0.095)
                        : rowHover.containsMouse
                            ? theme.alpha(root.textSecondary, 0.012)
                            : "transparent"
                    border.width: row.selected ? 1 : 0
                    border.color: row.selected ? theme.alpha(root.accent, 0.30) : "transparent"
                    Behavior on color { ColorAnimation { duration: 100 } }
                    Behavior on border.color { ColorAnimation { duration: 100 } }

                    Rectangle {
                        visible: row.selected
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.leftMargin: 18
                        anchors.rightMargin: 18
                        height: 1
                        color: theme.alpha(theme.foreground, 0.052)
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.leftMargin: 13
                    anchors.verticalCenter: parent.verticalCenter
                    width: 39
                    height: 39
                    radius: 10
                    color: row.selected
                        ? theme.alpha(root.mix(root.accent, root.textSecondary, 0.30), 0.055)
                        : theme.alpha(root.textSecondary, 0.032)
                    border.width: row.selected ? 1 : 0
                    border.color: row.selected ? theme.alpha(theme.foreground, 0.025) : "transparent"

                    Text {
                        anchors.centerIn: parent
                        text: String(row.index + 1).padStart(2, "0")
                        color: row.selected
                            ? theme.alpha(root.textPrimary, 0.92)
                            : theme.alpha(root.textSecondary, 0.84)
                        font.family: "Inter"
                        font.pixelSize: 13
                        font.weight: Font.Normal
                    }
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 65
                    anchors.right: parent.right
                    anchors.rightMargin: 58
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Text {
                        width: parent.width
                        text: String(row.modelData.preview || "")
                        color: root.textPrimary
                        elide: Text.ElideRight
                        maximumLineCount: 1
                        font.family: "Inter"
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }

                    Text {
                        width: parent.width
                        text: String(row.modelData.type || "Text")
                        color: root.textSecondary
                        elide: Text.ElideRight
                        font.family: "Inter"
                        font.pixelSize: 10
                    }
                }

                Rectangle {
                    id: pinButton
                    z: 3
                    anchors.right: parent.right
                    anchors.rightMargin: 13
                    anchors.verticalCenter: parent.verticalCenter
                    width: 34
                    height: 34
                    radius: 11
                    color: row.modelData.pinned
                        ? theme.alpha(root.mix(root.accent, root.textSecondary, 0.24), 0.13)
                        : pinHover.containsMouse
                            ? theme.alpha(root.textSecondary, 0.045)
                            : theme.alpha(root.textSecondary, 0.018)
                    border.width: 1
                    border.color: row.modelData.pinned
                        ? theme.alpha(root.accent, 0.26)
                        : theme.alpha(theme.foreground, pinHover.containsMouse ? 0.075 : 0.035)
                    opacity: row.revealPin
                        ? (root.clipboardState.mutating ? 0.48 : 1)
                        : 0
                    scale: row.revealPin ? 1 : 0.82

                    Behavior on opacity { NumberAnimation { duration: 110 } }
                    Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

                    ClipboardPinGlyph {
                        anchors.centerIn: parent
                        width: 17
                        height: 17
                        glyphColor: row.modelData.pinned
                            ? theme.alpha(root.textPrimary, 0.96)
                            : theme.alpha(root.textSecondary, pinHover.containsMouse ? 0.88 : 0.68)
                    }

                    MouseArea {
                        id: pinHover
                        anchors.fill: parent
                        enabled: !root.clipboardState.mutating
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: function(mouse) {
                            mouse.accepted = true
                            list.currentIndex = row.index
                            root.clipboardState.togglePin(row.modelData)
                        }
                    }
                }

                Rectangle {
                    visible: row.index < root.filteredItems.length - 1 && !row.selected
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.leftMargin: 66
                    anchors.rightMargin: 15
                    anchors.bottom: parent.bottom
                    height: 1
                    color: theme.alpha(theme.foreground, 0.034)
                }

                MouseArea {
                    id: rowHover
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        list.currentIndex = row.index
                        root.activateSelection()
                    }
                }
            }
        }

        Column {
            anchors.centerIn: parent
            spacing: 7
            visible: !root.clipboardState.loading && root.filteredItems.length === 0

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.clipboardState.errorText !== "" ? root.clipboardState.errorText : "No clipboard items"
                color: root.textSecondary
                font.family: "Inter"
                font.pixelSize: 12
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                visible: root.clipboardState.errorText === "" && root.query !== ""
                text: "Try a different filter"
                color: theme.alpha(root.textSecondary, 0.58)
                font.family: "Inter"
                font.pixelSize: 10
            }
        }
    }

    Connections {
        target: root.clipboardState
        function onSelectionCopied() { root.closeRequested() }
    }

    onShownChanged: {
        if (shown) {
            query = ""
            searchInput.text = ""
            searchInput.forceActiveFocus()
            root.clipboardState.refresh()
            resetSelectionToBeginning()
        }
    }
}
