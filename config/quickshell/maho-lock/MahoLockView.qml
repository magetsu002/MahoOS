import QtQuick
import QtQuick.Effects

FocusScope {
    id: root

    required property var theme
    required property var state
    required property var auth
    property bool previewMode: false

    property real revealProgress: 0
    property bool passwordVisible: false

    readonly property string currentTime: Qt.formatDateTime(clock.now, "HH:mm")
    readonly property string currentDate: Qt.formatDateTime(clock.now, "dddd, d MMMM")
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

    // 1600x1000 logical pixels is the native target composition. The user's
    // 2560x1600 display at 1.6 scale resolves to this exact logical size.
    readonly property real uiScale: Math.max(
        0.78,
        Math.min(1.18, Math.min(width / 1600, height / 1000))
    )

    // Lock typography is deliberately neutral white. Wallpaper-derived color
    // remains in the accent/material, but foreground contrast must not invert
    // when the active desktop palette happens to be a light palette.
    readonly property color textPrimary: Qt.rgba(1, 1, 1, 0.96)
    readonly property color textSecondary: Qt.rgba(1, 1, 1, 0.68)
    readonly property color textTertiary: Qt.rgba(1, 1, 1, 0.48)
    readonly property color glassFill: Qt.rgba(1, 1, 1, 0.055)
    readonly property color glassFillFocus: Qt.rgba(1, 1, 1, 0.085)
    readonly property color glassStroke: Qt.rgba(1, 1, 1, 0.17)

    focus: true

    function submitPassword() {
        if (passwordInput.text.length === 0 || auth.authenticating || auth.unlocking)
            return
        auth.submit(passwordInput.text)
    }

    function reclaimPasswordFocus() {
        if (!auth.unlocking)
            passwordInput.forceActiveFocus()
    }

    Component.onCompleted: {
        revealDelay.start()
        focusRecovery.restart()
    }

    Timer {
        id: revealDelay
        interval: 20
        repeat: false
        onTriggered: root.revealProgress = 1
    }

    // Session-lock surfaces can become keyboard-active after their QML tree has
    // completed. Retry focus for a short bounded period instead of assuming one
    // Component.onCompleted forceActiveFocus() call happened after map/focus.
    Timer {
        id: focusRecovery
        interval: 100
        repeat: true
        property int attempts: 0
        onTriggered: {
            if (auth.unlocking) {
                stop()
                return
            }
            passwordInput.forceActiveFocus()
            attempts += 1
            if (passwordInput.activeFocus || attempts >= 30)
                stop()
        }
    }

    Behavior on revealProgress {
        NumberAnimation {
            duration: 440
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

    // MultiEffect renders a second visual item. The source must not also be
    // drawn, otherwise the raw and blurred wallpaper stack and wash each other
    // out. Keep the source hidden and render only the effect below.
    Image {
        id: wallpaper
        anchors.fill: parent
        source: state.wallpaperUrl
        visible: false
        asynchronous: true
        cache: true
        fillMode: Image.PreserveAspectCrop
        sourceSize.width: root.width
        sourceSize.height: root.height
    }

    MultiEffect {
        anchors.fill: parent
        source: wallpaper
        visible: state.wallpaperIsImage && wallpaper.status === Image.Ready
        blurEnabled: true
        blur: 0.38
        blurMax: 32
        saturation: -0.10
        brightness: -0.15
        scale: auth.unlocking ? 1.014 : 1.026 - root.revealProgress * 0.026

        Behavior on scale {
            NumberAnimation {
                duration: auth.unlocking ? 210 : 520
                easing.type: Easing.OutCubic
            }
        }
    }

    // A restrained veil keeps the white lock typography readable across every
    // wallpaper without turning the lock screen into an opaque modal.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.025, 0.032, 0.045, auth.unlocking ? 0.17 : 0.25)

        Behavior on color {
            ColorAnimation { duration: 210 }
        }
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(0.03, 0.04, 0.06, 0.08) }
            GradientStop { position: 0.48; color: Qt.rgba(0.03, 0.04, 0.06, 0.01) }
            GradientStop { position: 1.00; color: Qt.rgba(0.02, 0.03, 0.05, 0.18) }
        }
    }

    Item {
        id: chrome
        anchors.fill: parent
        opacity: auth.unlocking ? 0 : Math.min(1, root.revealProgress * 1.45)
        transform: Translate {
            y: auth.unlocking
                ? -8 * root.uiScale
                : (1 - root.revealProgress) * 12 * root.uiScale
        }

        Behavior on opacity {
            NumberAnimation {
                duration: auth.unlocking ? 180 : 330
                easing.type: Easing.OutCubic
            }
        }

        // Top-center lock state.
        Row {
            anchors.top: parent.top
            anchors.topMargin: 23 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8 * root.uiScale

            Item {
                width: 14 * root.uiScale
                height: 16 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter

                Rectangle {
                    x: 2 * root.uiScale
                    y: 7 * root.uiScale
                    width: 10 * root.uiScale
                    height: 8 * root.uiScale
                    radius: 2 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }

                Rectangle {
                    x: 4 * root.uiScale
                    y: 1 * root.uiScale
                    width: 6 * root.uiScale
                    height: 9 * root.uiScale
                    radius: 3 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                }
            }

            Text {
                text: root.previewMode ? "Lock preview" : "Screen locked"
                color: root.textSecondary
                font.pixelSize: 13 * root.uiScale
                font.weight: Font.Normal
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        // Minimal status cluster.
        Row {
            anchors.top: parent.top
            anchors.topMargin: 22 * root.uiScale
            anchors.right: parent.right
            anchors.rightMargin: 28 * root.uiScale
            spacing: 15 * root.uiScale

            Item {
                width: 20 * root.uiScale
                height: 16 * root.uiScale
                visible: state.networkKind === "wifi"

                Canvas {
                    anchors.fill: parent
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.reset()
                        ctx.strokeStyle = root.textPrimary
                        ctx.fillStyle = root.textPrimary
                        ctx.lineWidth = Math.max(1.2, 1.4 * root.uiScale)
                        ctx.lineCap = "round"

                        ctx.beginPath()
                        ctx.arc(width / 2, 8 * root.uiScale, 8 * root.uiScale, Math.PI * 1.17, Math.PI * 1.83)
                        ctx.stroke()
                        ctx.beginPath()
                        ctx.arc(width / 2, 10 * root.uiScale, 5 * root.uiScale, Math.PI * 1.17, Math.PI * 1.83)
                        ctx.stroke()
                        ctx.beginPath()
                        ctx.arc(width / 2, 14 * root.uiScale, 1.3 * root.uiScale, 0, Math.PI * 2)
                        ctx.fill()
                    }
                }
            }

            Row {
                visible: state.batteryAvailable
                spacing: 5 * root.uiScale

                Item {
                    width: 24 * root.uiScale
                    height: 14 * root.uiScale
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
                            width: Math.max(1, (parent.width - 4 * root.uiScale) * state.batteryPercentage / 100)
                            height: parent.height - 4 * root.uiScale
                            radius: 1.2 * root.uiScale
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
                    text: state.batteryPercentage + "%"
                    color: root.textPrimary
                    font.pixelSize: 13 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                spacing: 6 * root.uiScale

                Rectangle {
                    width: 17 * root.uiScale
                    height: 12 * root.uiScale
                    radius: 2 * root.uiScale
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: root.textSecondary
                    anchors.verticalCenter: parent.verticalCenter

                    Row {
                        anchors.centerIn: parent
                        spacing: 1.5 * root.uiScale
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
                    text: state.keyboardLayout
                    color: root.textPrimary
                    font.pixelSize: 13 * root.uiScale
                    font.capitalization: Font.AllUppercase
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        // Exact target hierarchy. Explicit geometry avoids Column implicit-size
        // surprises on the session-lock surface and keeps all elements stable.
        Item {
            id: mainContent
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(138 * root.uiScale, parent.height * 0.15)
            width: 560 * root.uiScale
            height: 670 * root.uiScale
            scale: auth.unlocking ? 1.01 : 0.988 + root.revealProgress * 0.012

            Behavior on scale {
                NumberAnimation {
                    duration: auth.unlocking ? 190 : 440
                    easing.type: Easing.OutCubic
                }
            }

            Text {
                id: timeText
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.currentTime
                color: root.textPrimary
                font.pixelSize: 106 * root.uiScale
                font.weight: Font.Light
                font.letterSpacing: -1.8 * root.uiScale
            }

            Text {
                id: dateText
                anchors.top: parent.top
                anchors.topMargin: 166 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.currentDate
                color: root.textSecondary
                font.pixelSize: 18 * root.uiScale
                font.weight: Font.Normal
            }

            Text {
                id: greetingText
                anchors.top: parent.top
                anchors.topMargin: 258 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.greeting
                color: root.textPrimary
                font.pixelSize: 19 * root.uiScale
                font.weight: Font.Normal
            }

            Rectangle {
                id: avatar
                anchors.top: parent.top
                anchors.topMargin: 304 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 84 * root.uiScale
                height: width
                radius: width / 2
                color: theme.alpha(theme.accent, 0.78)
                border.width: Math.max(1, root.uiScale)
                border.color: Qt.rgba(1, 1, 1, 0.17)

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: -5 * root.uiScale
                    radius: width / 2
                    color: "transparent"
                    border.width: Math.max(1, root.uiScale)
                    border.color: Qt.rgba(1, 1, 1, 0.10)
                }

                Text {
                    anchors.centerIn: parent
                    text: state.displayName.length > 0
                        ? state.displayName.charAt(0).toUpperCase()
                        : "M"
                    color: root.textPrimary
                    font.pixelSize: 36 * root.uiScale
                    font.weight: Font.Light
                }
            }

            Item {
                id: authRegion
                anchors.top: parent.top
                anchors.topMargin: 438 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 430 * root.uiScale
                height: 160 * root.uiScale

                transform: Translate { id: shakeTranslate }

                SequentialAnimation {
                    id: shake
                    NumberAnimation { target: shakeTranslate; property: "x"; to: -7 * root.uiScale; duration: 45 }
                    NumberAnimation { target: shakeTranslate; property: "x"; to: 7 * root.uiScale; duration: 65 }
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
                    color: passwordInput.activeFocus ? root.glassFillFocus : root.glassFill
                    border.width: Math.max(1, root.uiScale)
                    border.color: passwordInput.activeFocus
                        ? Qt.rgba(1, 1, 1, 0.25)
                        : root.glassStroke

                    Behavior on color { ColorAnimation { duration: 110 } }
                    Behavior on border.color { ColorAnimation { duration: 110 } }

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
                        height: parent.height
                        verticalAlignment: TextInput.AlignVCenter
                        color: root.textPrimary
                        selectionColor: theme.alpha(theme.accent, 0.35)
                        selectedTextColor: root.textPrimary
                        font.pixelSize: 14 * root.uiScale
                        echoMode: root.passwordVisible ? TextInput.Normal : TextInput.Password
                        passwordCharacter: "●"
                        enabled: !auth.unlocking
                        focus: true
                        activeFocusOnPress: true
                        selectByMouse: true
                        clip: true
                        inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText

                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            visible: passwordInput.text.length === 0
                            text: auth.authenticating ? "Authenticating…" : "Enter your password"
                            color: root.textTertiary
                            font.pixelSize: 14 * root.uiScale
                        }

                        Keys.onPressed: function(event) {
                            if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                                root.submitPassword()
                                event.accepted = true
                            } else if (event.key === Qt.Key_Escape) {
                                if (root.previewMode)
                                    Qt.quit()
                                else
                                    passwordInput.clear()
                                event.accepted = true
                            }
                        }
                    }

                    Item {
                        id: eyeButton
                        anchors.right: parent.right
                        anchors.rightMargin: 17 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        width: 31 * root.uiScale
                        height: 31 * root.uiScale

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
                                root.reclaimPasswordFocus()
                            }
                        }
                    }

                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.LeftButton
                        propagateComposedEvents: true
                        onPressed: function(mouse) {
                            root.reclaimPasswordFocus()
                            mouse.accepted = false
                        }
                    }
                }

                Rectangle {
                    id: unlockButton
                    anchors.top: passwordShell.bottom
                    anchors.topMargin: 18 * root.uiScale
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 206 * root.uiScale
                    height: 50 * root.uiScale
                    radius: height / 2
                    color: unlockHover.containsMouse
                        ? Qt.rgba(1, 1, 1, 0.145)
                        : Qt.rgba(1, 1, 1, 0.105)
                    border.width: Math.max(1, root.uiScale)
                    border.color: Qt.rgba(1, 1, 1, 0.12)

                    Behavior on color { ColorAnimation { duration: 100 } }

                    Text {
                        anchors.centerIn: parent
                        text: auth.authenticating ? "Checking…" : "Unlock"
                        color: root.textPrimary
                        font.pixelSize: 14 * root.uiScale
                        font.weight: Font.DemiBold
                    }

                    MouseArea {
                        id: unlockHover
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: !auth.authenticating && !auth.unlocking
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.reclaimPasswordFocus()
                            root.submitPassword()
                        }
                    }
                }

                Text {
                    anchors.top: unlockButton.bottom
                    anchors.topMargin: 11 * root.uiScale
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: auth.errorText.length > 0
                        ? auth.errorText
                        : (root.previewMode ? "Esc closes preview" : "Press Enter to unlock")
                    color: auth.errorText.length > 0
                        ? theme.alpha(theme.error, 0.95)
                        : root.textSecondary
                    font.pixelSize: 11 * root.uiScale
                    font.weight: auth.errorText.length > 0 ? Font.Medium : Font.Normal
                }

                Connections {
                    target: auth

                    function onFailed() {
                        passwordInput.clear()
                        focusRecovery.attempts = 0
                        focusRecovery.restart()
                        shake.restart()
                    }
                }
            }
        }

        Rectangle {
            anchors.left: parent.left
            anchors.leftMargin: 28 * root.uiScale
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 28 * root.uiScale
            width: 105 * root.uiScale
            height: 40 * root.uiScale
            radius: height / 2
            color: sleepHover.containsMouse ? Qt.rgba(1, 1, 1, 0.055) : "transparent"

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 12 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "⏻"
                color: root.textPrimary
                font.pixelSize: 16 * root.uiScale
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 41 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "Sleep"
                color: root.textPrimary
                font.pixelSize: 13 * root.uiScale
            }

            MouseArea {
                id: sleepHover
                anchors.fill: parent
                hoverEnabled: true
                enabled: !root.previewMode
                cursorShape: Qt.PointingHandCursor
                onClicked: state.suspend()
            }
        }

        Rectangle {
            anchors.right: parent.right
            anchors.rightMargin: 28 * root.uiScale
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 28 * root.uiScale
            width: 132 * root.uiScale
            height: 40 * root.uiScale
            radius: height / 2
            visible: root.previewMode || state.switchUserCommand.length > 0
            color: switchHover.containsMouse ? Qt.rgba(1, 1, 1, 0.055) : "transparent"

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 12 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "◎"
                color: root.textPrimary
                font.pixelSize: 17 * root.uiScale
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 39 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                text: "Switch user"
                color: root.textPrimary
                font.pixelSize: 13 * root.uiScale
            }

            MouseArea {
                id: switchHover
                anchors.fill: parent
                hoverEnabled: true
                enabled: !root.previewMode && state.switchUserCommand.length > 0
                cursorShape: Qt.PointingHandCursor
                onClicked: state.switchUser()
            }
        }
    }
}
