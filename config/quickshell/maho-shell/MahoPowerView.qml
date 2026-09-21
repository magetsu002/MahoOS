import QtQuick

Item {
    id: root

    property var theme
    property var updateState
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
    readonly property int iconSize: compact ? 18 : 34
    readonly property int titleSize: compact ? 14 : 27
    readonly property int subtitleSize: compact ? 0 : 13
    readonly property int labelSize: compact ? 10 : 16
    readonly property int detailSize: compact ? 8 : 12

    function alpha(color, amount) {
        if (theme && theme.alpha)
            return theme.alpha(color, amount)
        return Qt.rgba(color.r, color.g, color.b, amount)
    }

    function blend(a, b, amount, opacity) {
        const t = Math.max(0, Math.min(1, amount))
        return Qt.rgba(
            a.r * (1 - t) + b.r * t,
            a.g * (1 - t) + b.g * t,
            a.b * (1 - t) + b.b * t,
            opacity
        )
    }

    function actionAt(index) {
        const actions = ["lock", "sleep", "switch-user", "restart", "logout", "shutdown"]
        return actions[Math.max(0, Math.min(actions.length - 1, index))]
    }

    function requiresConfirmation(action) {
        return action === "restart" || action === "shutdown"
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
        id: ambientRim
        anchors.fill: shell
        anchors.margins: root.compact ? -1 : -3
        radius: shell.radius + (root.compact ? 1 : 3)
        color: "transparent"
        border.width: 1
        border.color: root.theme
            ? root.alpha(root.theme.primary, root.compact ? 0.025 : 0.060)
            : Qt.rgba(0.56, 0.64, 1.0, root.compact ? 0.02 : 0.055)
        z: -1
    }

    Rectangle {
        id: shell
        anchors.fill: parent
        radius: root.outerRadius
        antialiasing: true
        color: root.theme
            ? root.blend(
                root.theme.surfaceHigh,
                root.theme.primary,
                root.compact ? 0.09 : 0.25,
                root.compact ? 0.90 : 0.34
              )
            : Qt.rgba(0.11, 0.13, 0.24, root.compact ? 0.91 : 0.36)
        border.width: 1
        border.color: root.theme
            ? root.alpha(root.theme.foreground, root.compact ? 0.075 : 0.145)
            : Qt.rgba(0.94, 0.95, 1.0, root.compact ? 0.07 : 0.14)

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: root.compact ? 96 : 235
            radius: parent.radius
            color: "transparent"
            gradient: Gradient {
                GradientStop {
                    position: 0.0
                    color: root.theme
                        ? root.blend(root.theme.primary, root.theme.foreground, 0.10, root.compact ? 0.075 : 0.225)
                        : Qt.rgba(0.45, 0.55, 1.0, root.compact ? 0.07 : 0.21)
                }
                GradientStop {
                    position: 0.36
                    color: root.theme
                        ? root.alpha(root.theme.primary, root.compact ? 0.032 : 0.082)
                        : Qt.rgba(0.42, 0.50, 1.0, root.compact ? 0.03 : 0.08)
                }
                GradientStop {
                    position: 0.72
                    color: root.theme
                        ? root.alpha(root.theme.tertiary, root.compact ? 0.010 : 0.028)
                        : Qt.rgba(0.90, 0.55, 0.75, root.compact ? 0.01 : 0.025)
                }
                GradientStop { position: 1.0; color: "transparent" }
            }
            opacity: 0.92
        }

        Rectangle {
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.topMargin: 1
            width: parent.width - (root.compact ? 26 : 58)
            height: 1
            radius: 1
            color: root.theme
                ? root.blend(root.theme.primary, root.theme.foreground, 0.70, root.compact ? 0.10 : 0.30)
                : Qt.rgba(0.95, 0.96, 1.0, root.compact ? 0.09 : 0.28)
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: root.compact ? 52 : 130
            radius: parent.radius
            color: "transparent"
            gradient: Gradient {
                GradientStop { position: 0.0; color: "transparent" }
                GradientStop {
                    position: 1.0
                    color: root.theme
                        ? root.alpha(root.theme.background, root.compact ? 0.08 : 0.055)
                        : Qt.rgba(0.02, 0.02, 0.06, root.compact ? 0.08 : 0.05)
                }
            }
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
                spacing: root.compact ? 0 : 7

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
                    color: root.theme ? root.alpha(root.theme.muted, 0.78) : "#b8c0dd"
                    font.pixelSize: root.subtitleSize
                    textFormat: Text.PlainText
                }

                Text {
                    visible: !root.compact && root.updateState
                        && (root.updateState.activationPending || root.updateState.attentionRequired)
                    text: root.updateState ? root.updateState.status : ""
                    color: root.theme ? root.alpha(root.theme.primary, 0.82) : "#b8c0dd"
                    font.pixelSize: root.subtitleSize
                    textFormat: Text.PlainText
                }
            }

            Rectangle {
                id: closeButton
                visible: root.closeButtonVisible
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: root.compact ? 30 : 50
                height: width
                radius: root.compact ? 10 : 17
                antialiasing: true
                color: root.theme
                    ? root.blend(
                        root.theme.surfaceHigh,
                        root.theme.primary,
                        closeHover.hovered ? 0.16 : 0.11,
                        closeHover.hovered ? 0.50 : 0.31
                      )
                    : Qt.rgba(0.20, 0.23, 0.36, closeHover.hovered ? 0.50 : 0.31)
                border.width: 1
                border.color: root.theme
                    ? root.alpha(root.theme.foreground, closeHover.hovered ? 0.14 : 0.075)
                    : Qt.rgba(1, 1, 1, closeHover.hovered ? 0.13 : 0.07)
                scale: closeTap.pressed ? 0.94 : 1

                Behavior on color { ColorAnimation { duration: 140 } }
                Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: root.theme ? root.alpha(root.theme.foreground, 0.90) : "#edf0ff"
                    font.pixelSize: root.compact ? 17 : 27
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
                color: root.theme ? root.alpha(root.theme.primary, 0.88) : "#b9c2ff"
                font.pixelSize: 8
                font.weight: Font.DemiBold
                font.letterSpacing: 0.7
            }

            Text {
                anchors.left: parent.horizontalCenter
                anchors.leftMargin: root.gridGap / 2
                text: "POWER"
                color: root.theme ? root.alpha(root.theme.primary, 0.88) : "#b9c2ff"
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
                readonly property bool highlighted: tileHover.hovered || tile.selected

                width: (grid.width - root.gridGap) / 2
                height: root.tileHeight
                radius: root.compact ? 13 : 20
                antialiasing: true

                color: tile.danger
                    ? (root.theme
                        ? root.blend(
                            root.theme.surfaceHigh,
                            root.theme.error,
                            tile.armed ? 0.48 : (tile.highlighted ? 0.40 : 0.27),
                            root.compact
                                ? (tile.armed ? 0.94 : (tile.highlighted ? 0.91 : 0.86))
                                : (tile.armed ? 0.52 : (tile.highlighted ? 0.45 : 0.36))
                          )
                        : Qt.rgba(
                            0.31, 0.14, 0.20,
                            root.compact
                                ? (tile.armed ? 0.94 : (tile.highlighted ? 0.91 : 0.86))
                                : (tile.armed ? 0.52 : (tile.highlighted ? 0.45 : 0.36))
                          ))
                    : tile.selected
                        ? (root.theme
                            ? root.blend(root.theme.surfaceHigh, root.theme.primary, 0.39, root.compact ? 0.86 : 0.42)
                            : Qt.rgba(0.20, 0.26, 0.53, root.compact ? 0.86 : 0.42))
                        : (root.theme
                            ? root.blend(
                                root.theme.surfaceHigh,
                                root.theme.primary,
                                tileHover.hovered ? 0.16 : 0.115,
                                root.compact ? 0.82 : 0.26
                              )
                            : Qt.rgba(0.17, 0.19, 0.29, root.compact ? 0.82 : 0.26))

                border.width: tile.selected || tile.armed ? 1.1 : 1
                border.color: tile.danger
                    ? root.alpha(
                        root.theme ? root.theme.error : "#ff5265",
                        tile.armed ? 0.72 : (tile.highlighted ? 0.52 : 0.24)
                      )
                    : tile.selected
                        ? root.alpha(root.theme ? root.theme.primary : "#8aa6ff", 0.54)
                        : root.alpha(root.theme ? root.theme.foreground : "white", tileHover.hovered ? 0.095 : 0.048)

                scale: tileTap.pressed ? 0.975 : 1

                Behavior on color { ColorAnimation { duration: 150 } }
                Behavior on border.color { ColorAnimation { duration: 150 } }
                Behavior on scale { NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }

                Rectangle {
                    visible: tile.selected && !tile.danger
                    anchors.fill: parent
                    anchors.margins: -3
                    radius: parent.radius + 3
                    color: root.alpha(root.theme ? root.theme.primary : "#8aa6ff", root.compact ? 0.025 : 0.060)
                    z: -1
                }

                Rectangle {
                    visible: tile.danger && (tile.highlighted || tile.armed)
                    anchors.fill: parent
                    anchors.margins: root.compact ? -2 : -4
                    radius: parent.radius + (root.compact ? 2 : 4)
                    color: root.alpha(
                        root.theme ? root.theme.error : "#ff5265",
                        tile.armed ? (root.compact ? 0.08 : 0.12)
                                   : (root.compact ? 0.045 : 0.075)
                    )
                    z: -1

                    Behavior on color { ColorAnimation { duration: 150 } }
                }

                Rectangle {
                    visible: tile.selected && !tile.danger
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: root.compact ? 10 : 18
                    anchors.rightMargin: root.compact ? 10 : 18
                    height: 1
                    color: root.alpha(root.theme ? root.theme.foreground : "white", root.compact ? 0.10 : 0.18)
                }

                Text {
                    id: glyphItem
                    anchors.left: parent.left
                    anchors.leftMargin: root.compact ? 14 : 34
                    anchors.verticalCenter: parent.verticalCenter
                    width: root.compact ? 25 : 44
                    horizontalAlignment: Text.AlignHCenter
                    text: tile.glyph
                    color: tile.danger
                        ? (root.theme
                            ? root.blend(root.theme.error, root.theme.foreground, tile.highlighted ? 0.16 : 0.0, 1.0)
                            : (tile.highlighted ? "#ff7f8d" : "#ff5265"))
                        : (root.theme ? root.blend(root.theme.primary, root.theme.foreground, tile.selected ? 0.28 : 0.16, 1.0) : "#b9c8ff")
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
                    spacing: root.compact ? 0 : 5

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
                            ? (root.theme ? root.alpha(root.theme.error, 0.88) : "#ff95a1")
                            : (root.theme ? root.alpha(root.theme.muted, 0.74) : "#adb5d0")
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
                glyph: "󰖔"
            }

            ActionTile {
                actionIndex: 2
                action: "switch-user"
                title: "Switch User"
                detail: "Sign in to another account"
                glyph: "󰀄"
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
