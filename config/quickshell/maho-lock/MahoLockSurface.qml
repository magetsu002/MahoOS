import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Wayland

WlSessionLockSurface {
    id: root

    required property var theme
    required property var state
    required property var auth

    color: theme.background

    property real revealProgress: 0
    property bool passwordVisible: false

    readonly property string currentTime:
        Qt.formatDateTime(clock.now, "HH:mm")
    readonly property string currentDate:
        Qt.formatDateTime(clock.now, "dddd, d MMMM")
    readonly property string greeting: {
        const hour = clock.now.getHours()
        if (hour < 5)
            return "Good night, " + state.displayName
        if (hour < 12)
            return "Good morning, " + state.displayName
        if (hour < 18)
            return "Good afternoon, " + state.displayName
        return "Good evening, " + state.displayName
    }

    readonly property real uiScale:
        Math.max(0.82, Math.min(1.12, Math.min(width / 1440, height / 900)))
    readonly property color textPrimary: theme.alpha(theme.foreground, 0.96)
    readonly property color textSecondary: theme.alpha(theme.foreground, 0.68)
    readonly property color glassStroke: theme.alpha(theme.foreground, 0.18)
    readonly property color glassFill:
        theme.alpha(theme.mix(theme.surfaceHigh, theme.background, 0.56), 0.34)

    function submitPassword() {
        if (passwordInput.text.length === 0 || auth.authenticating || auth.unlocking)
            return
        auth.submit(passwordInput.text)
    }

    Component.onCompleted: {
        revealProgress = 1
        Qt.callLater(function() { passwordInput.forceActiveFocus() })
    }

    Behavior on revealProgress {
        NumberAnimation {
            duration: 520
            easing.type: Easing.OutCubic
        }
    }

    Timer {
        id: clock
        interval: 1000
        repeat: true
        running: true
        triggeredOnStart: true
        property date now: new Date()
        onTriggered: now = new Date()
    }

    Rectangle {
        anchors.fill: parent
        color: theme.background
    }

    Image {
        id: wallpaper
        anchors.fill: parent
        source: state.wallpaperUrl
        visible: state.wallpaperIsImage
        asynchronous: true
        cache: true
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: root.width
        sourceSize.height: root.height
        scale: auth.unlocking
            ? 1.018
            : 1.035 - (root.revealProgress * 0.035)

        Behavior on scale {
            NumberAnimation {
                duration: auth.unlocking ? 240 : 650
                easing.type: Easing.OutCubic
            }
        }
    }

    MultiEffect {
        anchors.fill: parent
        source: wallpaper
        visible: wallpaper.visible && wallpaper.status === Image.Ready
        blurEnabled: true
        blur: 0.72
        blurMax: 56
        saturation: -0.12
        brightness: -0.08
    }

    Rectangle {
        id: atmosphericVeil
        anchors.fill: parent
        color: theme.alpha(theme.background, auth.unlocking ? 0.20 : 0.33)
        Behavior on color { ColorAnimation { duration: 240 } }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop {
                position: 0
                color: theme.alpha(theme.background, 0.12)
            }
            GradientStop {
                position: 0.48
                color: theme.alpha(theme.background, 0.03)
            }
            GradientStop {
                position: 1
                color: theme.alpha(theme.background, 0.27)
            }
        }
    }

    Item {
        id: chrome
        anchors.fill: parent
        opacity: auth.unlocking ? 0 : Math.min(1, root.revealProgress * 1.55)
        transform: Translate {
            y: auth.unlocking
                ? -10 * root.uiScale
                : (1 - root.revealProgress) * 14 * root.uiScale
        }

        Behavior on opacity {
            NumberAnimation {
                duration: auth.unlocking ? 190 : 360
                easing.type: Easing.OutCubic
            }
        }

        Item {
            id: lockedStatus
            anchors.top: parent.top
            anchors.topMargin: 20 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            width: 132 * root.uiScale
            height: 24 * root.uiScale

            Item {
                id: topLockGlyph
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 15 * root.uiScale
                height: 16 * root.uiScale

                Rectangle {
                    x: 3 * root.uiScale
                    y: 7 * root.uiScale
                    width: 9 * root.uiScale
                    height: 8 * root.uiScale
                    radius: 2 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }

                Rectangle {
                    x: 5 * root.uiScale
                    y: 2 * root.uiScale
                    width: 5 * root.uiScale
                    height: 8 * root.uiScale
                    radius: 3 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }
            }

            Text {
                anchors.left: topLockGlyph.right
                anchors.leftMargin: 8 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "Screen locked"
                color: root.textSecondary
                font.family: "Inter"
                font.pixelSize: 13 * root.uiScale
                font.weight: Font.Normal
            }
        }

        Row {
            anchors.top: parent.top
            anchors.topMargin: 20 * root.uiScale
            anchors.right: parent.right
            anchors.rightMargin: 24 * root.uiScale
            spacing: 14 * root.uiScale

            Item {
                width: 18 * root.uiScale
                height: 20 * root.uiScale
                visible: state.networkKind === "wifi"

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.reset()
                        ctx.strokeStyle = root.textPrimary
                        ctx.lineWidth = Math.max(1.2, 1.45 * root.uiScale)
                        ctx.lineCap = "round"

                        function arc(radius, y) {
                            ctx.beginPath()
                            ctx.arc(
                                width / 2,
                                y,
                                radius,
                                Math.PI * 1.16,
                                Math.PI * 1.84
                            )
                            ctx.stroke()
                        }

                        arc(8 * root.uiScale, 9 * root.uiScale)
                        arc(5 * root.uiScale, 11 * root.uiScale)

                        ctx.fillStyle = root.textPrimary
                        ctx.beginPath()
                        ctx.arc(width / 2, 15 * root.uiScale, 1.35 * root.uiScale, 0, Math.PI * 2)
                        ctx.fill()
                    }
                }
            }

            Row {
                visible: state.batteryAvailable
                spacing: 5 * root.uiScale

                Item {
                    width: 24 * root.uiScale
                    height: 13 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter

                    Rectangle {
                        x: 0
                        y: 1 * root.uiScale
                        width: 20 * root.uiScale
                        height: 11 * root.uiScale
                        radius: 2.5 * root.uiScale
                        color: "transparent"
                        border.width: Math.max(1, root.uiScale)
                        border.color: root.textPrimary

                        Rectangle {
                            anchors.left: parent.left
                            anchors.leftMargin: 2 * root.uiScale
                            anchors.verticalCenter: parent.verticalCenter
                            width: Math.max(
                                1,
                                (parent.width - 4 * root.uiScale)
                                * state.batteryPercentage / 100
                            )
                            height: parent.height - 4 * root.uiScale
                            radius: 1.3 * root.uiScale
                            color: root.textPrimary
                        }
                    }

                    Rectangle {
                        x: 21 * root.uiScale
                        y: 4 * root.uiScale
                        width: 2 * root.uiScale
                        height: 5 * root.uiScale
                        radius: root.uiScale
                        color: root.textPrimary
                    }
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: state.batteryPercentage + "%"
                    color: root.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 13 * root.uiScale
                }
            }

            Row {
                spacing: 6 * root.uiScale

                Rectangle {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 17 * root.uiScale
                    height: 12 * root.uiScale
                    radius: 2 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary

                    Row {
                        anchors.centerIn: parent
                        spacing: 1.4 * root.uiScale
                        Repeater {
                            model: 3
                            Rectangle {
                                width: 2 * root.uiScale
                                height: 2 * root.uiScale
                                radius: root.uiScale
                                color: root.textSecondary
                            }
                        }
                    }
                }

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: state.keyboardLayout
                    color: root.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 13 * root.uiScale
                    font.capitalization: Font.AllUppercase
                }
            }
        }

        Item {
            id: mainContent
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(108 * root.uiScale, parent.height * 0.155)
            width: Math.min(parent.width * 0.82, 620 * root.uiScale)
            height: 650 * root.uiScale
            scale: auth.unlocking ? 1.012 : 0.986 + root.revealProgress * 0.014

            Behavior on scale {
                NumberAnimation {
                    duration: auth.unlocking ? 210 : 520
                    easing.type: Easing.OutCubic
                }
            }

            Column {
                id: identityColumn
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 0

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.currentTime
                    color: root.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 100 * root.uiScale
                    font.weight: Font.ExtraLight
                    font.letterSpacing: -2.0 * root.uiScale
                }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    anchors.topMargin: -3 * root.uiScale
                    text: root.currentDate
                    color: root.textSecondary
                    font.family: "Inter"
                    font.pixelSize: 18 * root.uiScale
                    font.weight: Font.Normal
                }

                Item { width: 1; height: 48 * root.uiScale }

                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: root.greeting
                    color: root.textPrimary
                    font.family: "Inter"
                    font.pixelSize: 19 * root.uiScale
                    font.weight: Font.Normal
                }

                Item { width: 1; height: 16 * root.uiScale }

                Rectangle {
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 84 * root.uiScale
                    height: width
                    radius: width / 2
                    color: theme.alpha(theme.mix(theme.accent, theme.surfaceHigh, 0.16), 0.94)
                    border.width: Math.max(1, root.uiScale)
                    border.color: theme.alpha(theme.foreground, 0.18)

                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 5 * root.uiScale
                        radius: width / 2
                        color: "transparent"
                        border.width: Math.max(1, root.uiScale)
                        border.color: theme.alpha(theme.foreground, 0.10)
                    }

                    Text {
                        anchors.centerIn: parent
                        text: state.displayName.length > 0
                            ? state.displayName.charAt(0).toUpperCase()
                            : "M"
                        color: theme.alpha(theme.foreground, 0.96)
                        font.family: "Inter"
                        font.pixelSize: 34 * root.uiScale
                        font.weight: Font.Light
                    }
                }

                Item { width: 1; height: 22 * root.uiScale }

                Item {
                    id: authRegion
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 426 * root.uiScale
                    height: 154 * root.uiScale

                    transform: Translate { id: shakeTranslate }

                    SequentialAnimation {
                        id: shake
                        NumberAnimation { target: shakeTranslate; property: "x"; to: -7 * root.uiScale; duration: 45 }
                        NumberAnimation { target: shakeTranslate; property: "x"; to: 7 * root.uiScale; duration: 70 }
                        NumberAnimation { target: shakeTranslate; property: "x"; to: -4 * root.uiScale; duration: 55 }
                        NumberAnimation { target: shakeTranslate; property: "x"; to: 0; duration: 55 }
                    }

                    Rectangle {
                        id: passwordShell
                        anchors.top: parent.top
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: parent.width
                        height: 54 * root.uiScale
                        radius: height / 2
                        color: passwordInput.activeFocus
                            ? theme.alpha(theme.mix(theme.surfaceHigh, theme.accent, 0.04), 0.40)
                            : root.glassFill
                        border.width: Math.max(1, root.uiScale)
                        border.color: passwordInput.activeFocus
                            ? theme.alpha(theme.foreground, 0.23)
                            : root.glassStroke

                        Behavior on color { ColorAnimation { duration: 120 } }
                        Behavior on border.color { ColorAnimation { duration: 120 } }

                        Rectangle {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.leftMargin: 22 * root.uiScale
                            anchors.rightMargin: 22 * root.uiScale
                            height: Math.max(1, root.uiScale)
                            color: theme.alpha(theme.foreground, 0.08)
                        }

                        Item {
                            id: fieldLockGlyph
                            anchors.left: parent.left
                            anchors.leftMargin: 21 * root.uiScale
                            anchors.verticalCenter: parent.verticalCenter
                            width: 16 * root.uiScale
                            height: 18 * root.uiScale

                            Rectangle {
                                x: 3 * root.uiScale
                                y: 8 * root.uiScale
                                width: 10 * root.uiScale
                                height: 9 * root.uiScale
                                radius: 2 * root.uiScale
                                color: "transparent"
                                border.width: Math.max(1, root.uiScale)
                                border.color: root.textSecondary
                            }

                            Rectangle {
                                x: 5 * root.uiScale
                                y: 2 * root.uiScale
                                width: 6 * root.uiScale
                                height: 9 * root.uiScale
                                radius: 3 * root.uiScale
                                color: "transparent"
                                border.width: Math.max(1, root.uiScale)
                                border.color: root.textSecondary
                            }
                        }

                        TextInput {
                            id: passwordInput
                            anchors.left: fieldLockGlyph.right
                            anchors.leftMargin: 13 * root.uiScale
                            anchors.right: eyeButton.left
                            anchors.rightMargin: 10 * root.uiScale
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.textPrimary
                            selectionColor: theme.alpha(theme.accent, 0.30)
                            selectedTextColor: root.textPrimary
                            font.family: "Inter"
                            font.pixelSize: 13 * root.uiScale
                            echoMode: root.passwordVisible
                                ? TextInput.Normal
                                : TextInput.Password
                            passwordCharacter: "●"
                            enabled: !auth.unlocking
                            focus: true
                            clip: true

                            Text {
                                anchors.fill: parent
                                verticalAlignment: Text.AlignVCenter
                                visible: passwordInput.text.length === 0
                                text: auth.authenticating
                                    ? "Authenticating…"
                                    : "Enter your password"
                                color: theme.alpha(root.textSecondary, 0.75)
                                font: passwordInput.font
                            }

                            Keys.onPressed: function(event) {
                                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                    root.submitPassword()
                                    event.accepted = true
                                } else if (event.key === Qt.Key_Escape) {
                                    passwordInput.clear()
                                    event.accepted = true
                                }
                            }
                        }

                        Item {
                            id: eyeButton
                            anchors.right: parent.right
                            anchors.rightMargin: 18 * root.uiScale
                            anchors.verticalCenter: parent.verticalCenter
                            width: 30 * root.uiScale
                            height: 30 * root.uiScale

                            Canvas {
                                anchors.centerIn: parent
                                width: 19 * root.uiScale
                                height: 13 * root.uiScale
                                onPaint: {
                                    const ctx = getContext("2d")
                                    ctx.reset()
                                    ctx.strokeStyle = root.textSecondary
                                    ctx.lineWidth = Math.max(1, root.uiScale)
                                    ctx.beginPath()
                                    ctx.moveTo(1 * root.uiScale, height / 2)
                                    ctx.quadraticCurveTo(width / 2, -1 * root.uiScale, width - 1 * root.uiScale, height / 2)
                                    ctx.quadraticCurveTo(width / 2, height + 1 * root.uiScale, 1 * root.uiScale, height / 2)
                                    ctx.stroke()
                                    ctx.beginPath()
                                    ctx.arc(width / 2, height / 2, 2.2 * root.uiScale, 0, Math.PI * 2)
                                    ctx.stroke()
                                }
                            }

                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    root.passwordVisible = !root.passwordVisible
                                    passwordInput.forceActiveFocus()
                                }
                            }
                        }
                    }

                    Rectangle {
                        id: unlockButton
                        anchors.top: passwordShell.bottom
                        anchors.topMargin: 16 * root.uiScale
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 206 * root.uiScale
                        height: 50 * root.uiScale
                        radius: height / 2
                        color: unlockHover.containsMouse
                            ? theme.alpha(theme.mix(theme.surfaceHigh, theme.foreground, 0.10), 0.50)
                            : theme.alpha(theme.mix(theme.surfaceHigh, theme.foreground, 0.07), 0.43)
                        border.width: Math.max(1, root.uiScale)
                        border.color: theme.alpha(theme.foreground, 0.12)

                        Behavior on color { ColorAnimation { duration: 100 } }

                        Text {
                            anchors.centerIn: parent
                            text: auth.authenticating ? "Checking…" : "Unlock"
                            color: root.textPrimary
                            font.family: "Inter"
                            font.pixelSize: 14 * root.uiScale
                            font.weight: Font.DemiBold
                        }

                        MouseArea {
                            id: unlockHover
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !auth.authenticating && !auth.unlocking
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.submitPassword()
                        }
                    }

                    Text {
                        anchors.top: unlockButton.bottom
                        anchors.topMargin: 10 * root.uiScale
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: auth.errorText.length > 0
                            ? auth.errorText
                            : "Press Enter to unlock"
                        color: auth.errorText.length > 0
                            ? theme.alpha(theme.error, 0.92)
                            : theme.alpha(root.textSecondary, 0.92)
                        font.family: "Inter"
                        font.pixelSize: 11 * root.uiScale
                        font.weight: auth.errorText.length > 0 ? Font.Medium : Font.Normal
                    }

                    Connections {
                        target: auth

                        function onFailed() {
                            passwordInput.clear()
                            passwordInput.forceActiveFocus()
                            shake.restart()
                        }
                    }
                }
            }
        }

        Rectangle {
            id: sleepButton
            anchors.left: parent.left
            anchors.leftMargin: 26 * root.uiScale
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 28 * root.uiScale
            width: 96 * root.uiScale
            height: 38 * root.uiScale
            radius: height / 2
            color: sleepHover.containsMouse
                ? theme.alpha(theme.foreground, 0.055)
                : "transparent"

            Behavior on color { ColorAnimation { duration: 100 } }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 11 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "⏻"
                color: root.textPrimary
                font.pixelSize: 16 * root.uiScale
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 39 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "Sleep"
                color: root.textPrimary
                font.family: "Inter"
                font.pixelSize: 13 * root.uiScale
            }

            MouseArea {
                id: sleepHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: state.suspend()
            }
        }

        Rectangle {
            id: switchUserButton
            anchors.right: parent.right
            anchors.rightMargin: 26 * root.uiScale
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 28 * root.uiScale
            width: 126 * root.uiScale
            height: 38 * root.uiScale
            radius: height / 2
            visible: state.switchUserCommand.length > 0
            color: switchHover.containsMouse
                ? theme.alpha(theme.foreground, 0.055)
                : "transparent"

            Behavior on color { ColorAnimation { duration: 100 } }

            Item {
                anchors.left: parent.left
                anchors.leftMargin: 10 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                width: 22 * root.uiScale
                height: 20 * root.uiScale

                Rectangle {
                    x: 2 * root.uiScale
                    y: 2 * root.uiScale
                    width: 6 * root.uiScale
                    height: 6 * root.uiScale
                    radius: 3 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }

                Rectangle {
                    x: 12 * root.uiScale
                    y: 2 * root.uiScale
                    width: 6 * root.uiScale
                    height: 6 * root.uiScale
                    radius: 3 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }

                Rectangle {
                    x: 0
                    y: 10 * root.uiScale
                    width: 10 * root.uiScale
                    height: 7 * root.uiScale
                    radius: 4 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }

                Rectangle {
                    x: 10 * root.uiScale
                    y: 10 * root.uiScale
                    width: 10 * root.uiScale
                    height: 7 * root.uiScale
                    radius: 4 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 11 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "Switch user"
                color: root.textPrimary
                font.family: "Inter"
                font.pixelSize: 13 * root.uiScale
            }

            MouseArea {
                id: switchHover
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: state.switchUser()
            }
        }
    }
}
