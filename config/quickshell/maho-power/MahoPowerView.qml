import QtQuick

Item {
    id: root

    property var theme
    property bool compact: false
    property bool closeButtonVisible: true
    property bool keyboardNavigation: !compact
    property int selectedIndex: 0
    property string armedAction: ""

    signal closeRequested()
    signal actionRequested(string action)

    implicitWidth: compact ? 360 : 860
    implicitHeight: compact ? 276 : 570
    focus: keyboardNavigation

    readonly property real scaleFactor: compact ? 0.52 : 1.0
    readonly property int outerRadius: compact ? 20 : 34
    readonly property int outerPadding: compact ? 14 : 40
    readonly property int headerHeight: compact ? 42 : 92
    readonly property int gridGap: compact ? 7 : 16
    readonly property int rowGap: compact ? 7 : 18
    readonly property int tileHeight: compact ? 58 : 112
    readonly property int iconSize: compact ? 18 : 32
    readonly property int titleSize: compact ? 14 : 25
    readonly property int subtitleSize: compact ? 0 : 12
    readonly property int labelSize: compact ? 10 : 15
    readonly property int detailSize: compact ? 8 : 11

    function alpha(color, amount) {
        if (theme && theme.alpha)
            return theme.alpha(color, amount)
        return Qt.rgba(color.r, color.g, color.b, amount)
    }

    function actionAt(index) {
        const actions = ["lock", "sleep", "switch-user", "restart", "logout", "shutdown"]
        return actions[Math.max(0, Math.min(actions.length - 1, index))]
    }

    function requiresConfirmation(action) {
        return action === "logout" || action === "restart" || action === "shutdown"
    }

    function trigger(action) {
        if (requiresConfirmation(action)) {
            if (armedAction !== action) {
                armedAction = action
                confirmReset.restart()
                return
            }
        }

        confirmReset.stop()
        armedAction = ""
        actionRequested(action)
    }

    function moveSelection(dx, dy) {
        const column = selectedIndex % 2
        const row = Math.floor(selectedIndex / 2)
        const nextColumn = Math.max(0, Math.min(1, column + dx))
        const nextRow = Math.max(0, Math.min(2, row + dy))
        selectedIndex = nextRow * 2 + nextColumn
    }

    Keys.onPressed: function(event) {
        if (!keyboardNavigation)
            return

        if (event.key === Qt.Key_Escape) {
            closeRequested()
            event.accepted = true
        } else if (event.key === Qt.Key_Left) {
            moveSelection(-1, 0)
            event.accepted = true
        } else if (event.key === Qt.Key_Right) {
            moveSelection(1, 0)
            event.accepted = true
        } else if (event.key === Qt.Key_Up) {
            moveSelection(0, -1)
            event.accepted = true
        } else if (event.key === Qt.Key_Down) {
            moveSelection(0, 1)
            event.accepted = true
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
            trigger(actionAt(selectedIndex))
            event.accepted = true
        }
    }

    Timer {
        id: confirmReset
        interval: 2400
        onTriggered: root.armedAction = ""
    }

    Rectangle {
        id: shadow
        anchors.fill: shell
        anchors.margins: root.compact ? -2 : -12
        radius: shell.radius + (root.compact ? 2 : 10)
        color: Qt.rgba(0, 0, 0, root.compact ? 0.08 : 0.22)
        z: -2
    }

    Rectangle {
        id: shell
        anchors.fill: parent
        radius: root.outerRadius
        color: root.theme
            ? root.alpha(root.theme.surfaceHigh, root.compact ? 0.90 : 0.72)
            : Qt.rgba(0.09, 0.10, 0.16, root.compact ? 0.93 : 0.76)
        border.width: 1
        border.color: root.theme
            ? root.alpha(root.theme.outline, root.compact ? 0.28 : 0.44)
            : Qt.rgba(0.72, 0.76, 0.92, 0.34)

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: Math.max(1, parent.radius - 1)
            color: "transparent"
            border.width: 1
            border.color: root.theme
                ? root.alpha(root.theme.foreground, root.compact ? 0.035 : 0.08)
                : Qt.rgba(1, 1, 1, 0.07)
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: root.compact ? 68 : 170
            radius: parent.radius
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.0
                    color: root.theme
                        ? root.alpha(root.theme.primary, root.compact ? 0.035 : 0.09)
                        : Qt.rgba(0.32, 0.42, 0.90, 0.10)
                }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.86
        }

        Item {
            id: header
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: root.outerPadding
            anchors.rightMargin: root.outerPadding
            anchors.topMargin: root.compact ? 10 : 28
            height: root.headerHeight

            Column {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: root.compact ? 0 : 6

                Text {
                    text: "Power & Session"
                    color: root.theme ? root.theme.foreground : "#f4f3ff"
                    font.pixelSize: root.titleSize
                    font.weight: Font.DemiBold
                    textFormat: Text.PlainText
                }

                Text {
                    visible: !root.compact
                    text: "Choose an action"
                    color: root.theme ? root.alpha(root.theme.muted, 0.72) : "#aeb4ce"
                    font.pixelSize: root.subtitleSize
                    textFormat: Text.PlainText
                }
            }

            Rectangle {
                id: closeButton
                visible: root.closeButtonVisible
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: root.compact ? 30 : 48
                height: width
                radius: root.compact ? 10 : 16
                color: closeHover.hovered
                    ? (root.theme ? root.alpha(root.theme.foreground, 0.09) : Qt.rgba(1, 1, 1, 0.09))
                    : (root.theme ? root.alpha(root.theme.foreground, 0.045) : Qt.rgba(1, 1, 1, 0.045))
                border.width: 1
                border.color: root.theme ? root.alpha(root.theme.outline, 0.14) : Qt.rgba(1, 1, 1, 0.10)
                scale: closeTap.pressed ? 0.94 : 1

                Behavior on color { ColorAnimation { duration: 140 } }
                Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: root.theme ? root.alpha(root.theme.foreground, 0.82) : "#e6e7f4"
                    font.pixelSize: root.compact ? 17 : 26
                    textFormat: Text.PlainText
                }

                HoverHandler { id: closeHover }
                TapHandler {
                    id: closeTap
                    onTapped: root.closeRequested()
                }
            }
        }

        Item {
            id: labels
            visible: root.compact
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: header.bottom
            anchors.leftMargin: root.outerPadding
            anchors.rightMargin: root.outerPadding
            height: 18

            Text {
                anchors.left: parent.left
                text: "SESSION"
                color: root.theme ? root.alpha(root.theme.primary, 0.82) : "#aeb9ff"
                font.pixelSize: 8
                font.weight: Font.DemiBold
                font.letterSpacing: 0.7
            }

            Text {
                anchors.left: parent.horizontalCenter
                anchors.leftMargin: root.gridGap / 2
                text: "POWER"
                color: root.theme ? root.alpha(root.theme.primary, 0.82) : "#aeb9ff"
                font.pixelSize: 8
                font.weight: Font.DemiBold
                font.letterSpacing: 0.7
            }
        }

        Grid {
            id: grid
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: root.compact ? labels.bottom : header.bottom
            anchors.leftMargin: root.outerPadding
            anchors.rightMargin: root.outerPadding
            anchors.topMargin: root.compact ? 2 : 12
            columns: 2
            columnSpacing: root.gridGap
            rowSpacing: root.rowGap

            component ActionTile: Rectangle {
                id: tile
                required property int actionIndex
                required property string action
                required property string title
                required property string detail
                required property string glyph
                property bool danger: false

                readonly property bool selected: root.keyboardNavigation && root.selectedIndex === actionIndex
                readonly property bool armed: root.armedAction === action

                width: (grid.width - root.gridGap) / 2
                height: root.tileHeight
                radius: root.compact ? 13 : 20

                color: danger
                    ? root.alpha(root.theme ? root.theme.error : "#ff5265", armed ? 0.24 : (tileHover.hovered ? 0.19 : 0.13))
                    : selected
                        ? root.alpha(root.theme ? root.theme.primary : "#8aa6ff", 0.16)
                        : root.alpha(root.theme ? root.theme.foreground : "white", tileHover.hovered ? 0.075 : 0.045)

                border.width: selected || armed ? 1.3 : 1
                border.color: danger
                    ? root.alpha(root.theme ? root.theme.error : "#ff5265", armed ? 0.66 : 0.30)
                    : selected
                        ? root.alpha(root.theme ? root.theme.primary : "#8aa6ff", 0.82)
                        : root.alpha(root.theme ? root.theme.outline : "#9ba0b5", tileHover.hovered ? 0.26 : 0.14)

                scale: tileTap.pressed ? 0.975 : 1

                Behavior on color { ColorAnimation { duration: 150 } }
                Behavior on border.color { ColorAnimation { duration: 150 } }
                Behavior on scale { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }

                Rectangle {
                    visible: tile.selected && !tile.danger
                    anchors.fill: parent
                    anchors.margins: root.compact ? 2 : 3
                    radius: Math.max(1, parent.radius - 3)
                    color: "transparent"
                    border.width: 1
                    border.color: root.alpha(root.theme ? root.theme.primary : "#8aa6ff", 0.16)
                }

                Text {
                    id: glyphItem
                    anchors.left: parent.left
                    anchors.leftMargin: root.compact ? 14 : 34
                    anchors.verticalCenter: parent.verticalCenter
                    width: root.compact ? 25 : 42
                    horizontalAlignment: Text.AlignHCenter
                    text: tile.glyph
                    color: tile.danger
                        ? (root.theme ? root.theme.error : "#ff5265")
                        : (root.theme ? root.theme.primary : "#aab8ff")
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: root.iconSize
                    textFormat: Text.PlainText
                }

                Column {
                    anchors.left: glyphItem.right
                    anchors.leftMargin: root.compact ? 9 : 24
                    anchors.right: parent.right
                    anchors.rightMargin: root.compact ? 8 : 22
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: root.compact ? 0 : 4

                    Text {
                        width: parent.width
                        text: tile.title
                        color: root.theme ? root.theme.foreground : "#f2f1fb"
                        font.pixelSize: root.labelSize
                        font.weight: Font.Medium
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }

                    Text {
                        width: parent.width
                        text: tile.armed ? "Press again to confirm" : tile.detail
                        color: tile.armed && tile.danger
                            ? (root.theme ? root.alpha(root.theme.error, 0.84) : "#ff95a1")
                            : (root.theme ? root.alpha(root.theme.muted, 0.68) : "#a5aac0")
                        font.pixelSize: root.detailSize
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                    }
                }

                HoverHandler {
                    id: tileHover
                    onHoveredChanged: {
                        if (hovered && root.keyboardNavigation)
                            root.selectedIndex = tile.actionIndex
                    }
                }

                TapHandler {
                    id: tileTap
                    onTapped: {
                        root.selectedIndex = tile.actionIndex
                        root.trigger(tile.action)
                    }
                }
            }

            ActionTile {
                actionIndex: 0
                action: "lock"
                title: "Lock"
                detail: "Lock this session"
                glyph: "󰌾"
            }

            ActionTile {
                actionIndex: 1
                action: "sleep"
                title: "Sleep"
                detail: "Sleep until wake"
                glyph: "󰒲"
            }

            ActionTile {
                actionIndex: 2
                action: "switch-user"
                title: "Switch User"
                detail: "Sign in to another account"
                glyph: "󰀉"
            }

            ActionTile {
                actionIndex: 3
                action: "restart"
                title: "Restart"
                detail: "Restart system"
                glyph: "󰑓"
            }

            ActionTile {
                actionIndex: 4
                action: "logout"
                title: "Log Out"
                detail: "End current session"
                glyph: "󰍃"
            }

            ActionTile {
                actionIndex: 5
                action: "shutdown"
                title: "Shut Down"
                detail: "Power off completely"
                glyph: "󰐥"
                danger: true
            }
        }
    }

    Component.onCompleted: {
        if (keyboardNavigation)
            forceActiveFocus()
    }
}
