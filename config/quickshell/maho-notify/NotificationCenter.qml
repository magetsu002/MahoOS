import QtQuick

Item {
    id: center

    required property var theme
    required property var historyModel
    required property var identityResolver
    required property real availableHeight
    property bool adaptiveQuiet: false
    property string adaptiveContext: ""
    property bool shown: false
    property date timeReference: new Date()
    property string openMenuId: ""
    property bool controlMenuOpen: false

    signal closeRequested()
    signal adaptiveQuietStopRequested()

    width: 520
    height: Math.min(900, Math.max(460, availableHeight - 92))
    focus: shown
    opacity: shown ? 1 : 0
    scale: 1

    readonly property string focusContext: adaptiveContext.length > 0 ? adaptiveContext : historyModel.heldContext
    readonly property bool deliveryRestricted: historyModel.dndEnabled || adaptiveQuiet
    readonly property string controlTitle: historyModel.dndEnabled
        ? "Do Not Disturb"
        : (adaptiveQuiet
            ? (center.focusContext.length > 0
                ? "Adaptive Focus · " + center.focusContext
                : "Adaptive Focus")
            : (historyModel.heldCount > 0
                ? "Notification delivery · Holding"
                : "Notification delivery · Normal"))
    readonly property string controlSubtitle: historyModel.dndEnabled
        ? "Noncritical notifications are being held."
        : (adaptiveQuiet
            ? (center.focusContext === "Gaming"
                ? "Keeping distractions quiet while you game."
                : (center.focusContext === "Media"
                    ? "Keeping interruptions quiet while media is active."
                    : (center.focusContext === "Focus"
                        ? "Keeping noncritical interruptions quiet while you focus."
                        : "Maho is holding interruptions for your current activity.")))
            : (historyModel.heldCount > 0
                ? "Some notifications are being held by your app rules."
                : "Apps can notify you normally. Critical alerts always pass."))
    readonly property string controlIcon: historyModel.dndEnabled
        ? "󰂛"
        : (adaptiveQuiet
            ? (center.focusContext === "Gaming" ? "󰊴"
                : (center.focusContext === "Media" ? "󰎆" : "󰒲"))
            : (historyModel.heldCount > 0 ? "󰋚" : "󰂚"))
    readonly property string controlCountText: historyModel.heldCount > 0
        ? String(historyModel.heldCount) + " held"
        : (historyModel.unreadCount > 0 ? String(historyModel.unreadCount) + " unread" : "")

    // Keep the glass shell itself at final geometry so compositor diffusion
    // never leaves a moving blur footprint. The shell fades in while the
    // foreground content settles a few pixels into place below.
    Behavior on opacity {
        NumberAnimation { duration: center.shown ? 240 : 120; easing.type: Easing.OutCubic }
    }

    function dismissMenus() {
        openMenuId = ""
        controlMenuOpen = false
    }

    function focusHeldSection() {
        if (historyModel.heldCount <= 0 || historyList.count <= 0)
            return
        openMenuId = ""
        historyList.currentIndex = 0
        historyList.positionViewAtIndex(0, ListView.Beginning)
        historyList.forceActiveFocus()
    }

    function relativeTimestamp(timestamp) {
        const ageSeconds = Math.max(0, Math.floor((timeReference.getTime() - Number(timestamp)) / 1000))
        if (ageSeconds < 45)
            return "now"
        if (ageSeconds < 3600)
            return String(Math.floor(ageSeconds / 60)) + "m ago"
        if (ageSeconds < 86400)
            return String(Math.floor(ageSeconds / 3600)) + "h ago"
        return Qt.formatDate(new Date(Number(timestamp)), "MMM d")
    }

    function selectOffset(offset) {
        if (historyList.count <= 0)
            return
        historyList.currentIndex = Math.max(0, Math.min(historyList.count - 1, historyList.currentIndex + offset))
        historyList.positionViewAtIndex(historyList.currentIndex, ListView.Contain)
        openMenuId = ""
    }

    Keys.onEscapePressed: {
        if (openMenuId !== "" || controlMenuOpen)
            dismissMenus()
        else
            center.closeRequested()
    }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_D) {
            historyModel.toggleDnd()
            event.accepted = true
        } else if (event.key === Qt.Key_R) {
            historyModel.markAllRead()
            event.accepted = true
        } else if (event.key === Qt.Key_Delete) {
            historyModel.clearRead()
            event.accepted = true
        } else if (event.key === Qt.Key_Down || event.key === Qt.Key_J) {
            selectOffset(1)
            event.accepted = true
        } else if (event.key === Qt.Key_Up || event.key === Qt.Key_K) {
            selectOffset(-1)
            event.accepted = true
        } else if ((event.key === Qt.Key_Return || event.key === Qt.Key_Space)
                   && historyList.currentItem && historyList.currentItem.entry) {
            const entryId = String(historyList.currentItem.entry.id)
            if (historyModel.activateEntry(entryId))
                center.closeRequested()
            else
                historyList.currentItem.expanded = !historyList.currentItem.expanded
            event.accepted = true
        }
    }

    Timer {
        interval: 60000
        repeat: true
        running: center.shown
        onTriggered: center.timeReference = new Date()
    }

    Rectangle {
        id: material
        anchors.fill: parent
        radius: 22
        antialiasing: true
        color: theme.centerFill
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
                GradientStop { position: 0.18; color: theme.shellAccentWash }
                GradientStop { position: 0.56; color: "transparent" }
                GradientStop { position: 1.00; color: theme.shellBottomShade }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            anchors.top: parent.top
            height: 1
            radius: 1
            color: theme.shellInnerLine
        }

        Column {
            id: content
            anchors.fill: parent
            anchors.leftMargin: 28
            anchors.rightMargin: 28
            anchors.topMargin: 20
            anchors.bottomMargin: 20
            spacing: 12

            // Keep the blur footprint stationary while the foreground visibly
            // resolves into place. The larger but still restrained offset makes
            // the entrance readable at 240 Hz instead of looking like a pop.
            opacity: center.shown ? 1 : 0.18
            transform: Translate {
                id: contentReveal
                y: center.shown ? 0 : -14

                Behavior on y {
                    NumberAnimation { duration: center.shown ? 270 : 110; easing.type: Easing.OutCubic }
                }
            }

            Behavior on opacity {
                NumberAnimation { duration: center.shown ? 230 : 100; easing.type: Easing.OutCubic }
            }

            Item {
                id: header
                width: parent.width
                height: 48

                Text {
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "Notifications"
                    color: theme.textPrimary
                    font.pixelSize: 26
                    font.weight: Font.DemiBold
                    textFormat: Text.PlainText
                }

                Rectangle {
                    id: closeButton
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 30
                    height: 30
                    radius: 10
                    color: closeMouse.pressed
                        ? theme.controlPressed
                        : (closeMouse.containsMouse ? theme.controlHover : "transparent")
                    border.width: closeMouse.containsMouse ? 1 : 0
                    border.color: theme.controlRim

                    Behavior on color { ColorAnimation { duration: 110; easing.type: Easing.OutCubic } }

                    Text {
                        anchors.fill: parent
                        text: "×"
                        color: theme.textSecondary
                        font.pixelSize: 18
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        textFormat: Text.PlainText
                    }

                    MouseArea {
                        id: closeMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: center.closeRequested()
                    }
                }
            }

            Rectangle {
                id: controlCard
                width: parent.width
                height: 70
                radius: 16
                antialiasing: true
                color: controlBody.containsMouse || center.controlMenuOpen
                    ? theme.focusHover : theme.focusFill
                border.width: 1
                border.color: center.controlMenuOpen || center.deliveryRestricted
                    ? theme.controlRimActive : theme.focusRim

                Behavior on color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }
                Behavior on border.color { ColorAnimation { duration: 135; easing.type: Easing.OutCubic } }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 1
                    radius: 15
                    color: "transparent"
                    gradient: Gradient {
                        GradientStop { position: 0.00; color: theme.controlTopWash }
                        GradientStop { position: 0.48; color: "transparent" }
                        GradientStop { position: 1.00; color: theme.controlBottomShade }
                    }
                }

                Item {
                    id: controlIconBox
                    anchors.left: parent.left
                    anchors.leftMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    width: 28
                    height: 28

                    Text {
                        anchors.fill: parent
                        text: center.controlIcon
                        color: center.deliveryRestricted ? theme.accent : theme.textSecondary
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 17
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        textFormat: Text.PlainText
                    }
                }

                Column {
                    id: controlText
                    anchors.left: controlIconBox.right
                    anchors.leftMargin: 14
                    anchors.right: controlMeta.left
                    anchors.rightMargin: 18
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 4

                    Text {
                        width: parent.width
                        text: center.controlTitle
                        color: theme.textPrimary
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }
                    Text {
                        width: parent.width
                        text: center.controlSubtitle
                        color: theme.textMuted
                        font.pixelSize: 10
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }
                }

                // Reserve a fixed metadata lane so the held/unread count never
                // shifts when the hover affordance appears. The chevron is only
                // an affordance for the already-clickable card, not a second button.
                Item {
                    id: controlMeta
                    anchors.right: parent.right
                    anchors.rightMargin: 18
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 88

                    Item {
                        id: controlChevronLane
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18
                        height: 28

                        Text {
                            id: controlChevron
                            anchors.centerIn: parent
                            text: "›"
                            color: theme.textMuted
                            font.pixelSize: 18
                            font.weight: Font.Medium
                            opacity: controlBody.containsMouse || center.controlMenuOpen ? 1 : 0
                            scale: controlBody.containsMouse || center.controlMenuOpen ? 1 : 0.88
                            textFormat: Text.PlainText

                            transform: Translate {
                                x: controlBody.containsMouse || center.controlMenuOpen ? 0 : -4
                                Behavior on x {
                                    NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
                                }
                            }

                            Behavior on opacity {
                                NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                            }
                            Behavior on scale {
                                NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
                            }
                        }
                    }

                    Text {
                        anchors.right: controlChevronLane.left
                        anchors.rightMargin: 10
                        anchors.verticalCenter: parent.verticalCenter
                        visible: center.controlCountText.length > 0
                        text: center.controlCountText
                        color: theme.textSecondary
                        font.pixelSize: 10
                        font.weight: Font.Medium
                        horizontalAlignment: Text.AlignRight
                        textFormat: Text.PlainText
                    }
                }

                MouseArea {
                    id: controlBody
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        center.openMenuId = ""
                        center.controlMenuOpen = !center.controlMenuOpen
                    }
                }
            }

            Item {
                id: historyArea
                width: parent.width
                height: parent.height - header.height - controlCard.height - 24

                ListView {
                    id: historyList
                    anchors.fill: parent
                    clip: true
                    spacing: 6
                    reuseItems: true
                    cacheBuffer: 640
                    boundsBehavior: Flickable.StopAtBounds
                    keyNavigationEnabled: true
                    highlightMoveDuration: 120
                    model: historyModel.groupedEntries
                    visible: historyModel.loaded && historyModel.retainedCount > 0

                    onMovementStarted: {
                        center.openMenuId = ""
                        center.controlMenuOpen = false
                    }

                    section.property: "section"
                    section.criteria: ViewSection.FullString
                    section.delegate: Item {
                        required property string section
                        width: historyList.width
                        height: 64

                        Column {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 8
                            spacing: 3

                            Text {
                                text: parent.parent.section
                                color: theme.textPrimary
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                                textFormat: Text.PlainText
                            }
                            Text {
                                width: parent.width
                                text: parent.parent.section === "Held"
                                    ? "These notifications are saved and won't interrupt you."
                                    : "Normal notifications from your apps."
                                color: theme.textFaint
                                font.pixelSize: 10
                                elide: Text.ElideRight
                                textFormat: Text.PlainText
                            }
                        }
                    }

                    delegate: HistoryRow {
                        required property var modelData
                        required property int index
                        width: historyList.width
                        theme: center.theme
                        identityResolver: center.identityResolver
                        controller: center
                        entry: modelData
                        relativeTimestamp: center.relativeTimestamp(modelData.timestamp)
                        menuOpen: center.openMenuId === String(modelData.id)

                        onActivated: {
                            historyList.currentIndex = index
                            controller.openMenuId = ""
                            controller.controlMenuOpen = false
                            if (historyModel.activateEntry(String(modelData.id)))
                                controller.closeRequested()
                            else
                                expanded = !expanded
                        }
                        onMenuToggleRequested: entryId => {
                            historyList.currentIndex = index
                            controller.controlMenuOpen = false
                            controller.openMenuId = controller.openMenuId === entryId ? "" : entryId
                        }
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    visible: !historyModel.loaded

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 38
                        height: 38
                        radius: 13
                        color: theme.badgeFill
                        border.width: 1
                        border.color: theme.badgeRim

                        Text {
                            anchors.centerIn: parent
                            text: "󰔟"
                            color: theme.textSecondary
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 15
                            textFormat: Text.PlainText
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Loading notifications…"
                        color: theme.textMuted
                        font.pixelSize: 10
                        textFormat: Text.PlainText
                    }
                }

                Column {
                    anchors.centerIn: parent
                    spacing: 8
                    visible: historyModel.loaded && historyModel.retainedCount === 0

                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 42
                        height: 42
                        radius: 14
                        color: theme.badgeFill
                        border.width: 1
                        border.color: theme.badgeRim

                        Text {
                            anchors.centerIn: parent
                            text: "󰂚"
                            color: theme.textSecondary
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 17
                            textFormat: Text.PlainText
                        }
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "All clear"
                        color: theme.textPrimary
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        textFormat: Text.PlainText
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "No notifications in history."
                        color: theme.textFaint
                        font.pixelSize: 9
                        textFormat: Text.PlainText
                    }
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: -6
                    width: 2
                    radius: 1
                    color: theme.alpha(theme.foreground, 0.28)
                    visible: historyList.visible && historyList.moving && historyList.contentHeight > historyList.height
                    height: Math.max(26, historyList.height * historyList.height / historyList.contentHeight)
                    y: historyList.contentHeight <= historyList.height
                        ? 0
                        : (historyList.contentY / (historyList.contentHeight - historyList.height))
                            * (historyList.height - height)
                }
            }
        }

        // Popovers should never become sticky. While either menu is open this
        // transparent backdrop sits above normal center content but below both
        // menu surfaces, so any outside click dismisses the active dropdown.
        MouseArea {
            id: menuDismissLayer
            anchors.fill: parent
            z: 480
            visible: center.openMenuId !== "" || center.controlMenuOpen
            enabled: visible
            onClicked: center.dismissMenus()
        }

        NotificationControlMenu {
            id: notificationControlMenu
            z: 520
            theme: center.theme
            opened: center.controlMenuOpen
            dndEnabled: historyModel.dndEnabled
            adaptiveQuiet: center.adaptiveQuiet
            heldCount: historyModel.heldCount
            unreadCount: historyModel.unreadCount
            retainedCount: historyModel.retainedCount
            policyCount: historyModel.policyCount
            x: material.width - width - 28
            y: 20 + header.height + 12 + controlCard.height + 6
            onDndToggleRequested: historyModel.toggleDnd()
            onAdaptiveStopRequested: {
                center.controlMenuOpen = false
                center.adaptiveQuietStopRequested()
            }
            onReviewRequested: {
                center.controlMenuOpen = false
                center.focusHeldSection()
            }
            onReleaseRequested: {
                center.controlMenuOpen = false
                historyModel.releaseAllHeld()
            }
            onMarkAllReadRequested: historyModel.markAllRead()
            onClearReadRequested: historyModel.clearReadHistory()
            onResetRulesRequested: historyModel.clearAppPolicies()
        }

        // One menu surface for the whole center avoids one hidden menu per row,
        // stays above the clipped ListView, and keeps actions usable near the bottom.
        NotificationActionMenu {
            id: centerActionMenu
            z: 500
            theme: center.theme
            opened: center.openMenuId !== "" && historyList.currentItem !== null
            currentMode: historyList.currentItem && historyList.currentItem.entry
                ? String(historyList.currentItem.entry.deliveryMode || "") : ""
            x: {
                if (!historyList.currentItem || !historyList.currentItem.menuAnchorFor)
                    return material.width - width - 16
                const point = historyList.currentItem.menuAnchorFor(material)
                return Math.max(16, Math.min(material.width - width - 16, point.x - width + 18))
            }
            y: {
                if (!historyList.currentItem || !historyList.currentItem.menuAnchorFor)
                    return 16
                const point = historyList.currentItem.menuAnchorFor(material)
                return Math.max(16, Math.min(material.height - height - 16, point.y + 12))
            }
            onActionTriggered: action => {
                if (!historyList.currentItem || !historyList.currentItem.entry)
                    return
                const entryId = String(historyList.currentItem.entry.id)
                center.openMenuId = ""
                historyModel.presentationAction(entryId, action, center.adaptiveQuiet, center.focusContext)
            }
        }
    }
}
