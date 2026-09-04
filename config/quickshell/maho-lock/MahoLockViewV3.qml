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

    readonly property real uiScale: Math.max(
        0.78,
        Math.min(1.18, Math.min(width / 1600, height / 1000))
    )

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

    readonly property color textPrimary: Qt.rgba(1, 1, 1, 0.965)
    readonly property color textSecondary: Qt.rgba(1, 1, 1, 0.72)
    readonly property color textTertiary: Qt.rgba(1, 1, 1, 0.52)

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

    Timer {
        id: clock
        interval: 1000
        repeat: true
        running: true
        triggeredOnStart: true
        property date now: new Date()
        onTriggered: now = new Date()
    }

    Behavior on revealProgress {
        NumberAnimation {
            duration: 460
            easing.type: Easing.OutCubic
        }
    }

    Rectangle {
        anchors.fill: parent
        z: -5
        color: theme.background
    }

    // The wallpaper is captured into an offscreen texture and hidden by the
    // capture object, rather than by setting Image.visible=false. This keeps a
    // valid texture source for MultiEffect without drawing a second raw copy.
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
    }

    ShaderEffectSource {
        id: wallpaperTexture
        anchors.fill: parent
        sourceItem: wallpaper
        hideSource: true
        live: true
        visible: false
    }

    MultiEffect {
        id: wallpaperEffect
        anchors.fill: parent
        z: -4
        source: wallpaperTexture
        visible: state.wallpaperIsImage && wallpaper.status === Image.Ready
        blurEnabled: true
        blur: 0.31
        blurMax: 36
        saturation: -0.025
        brightness: 0.005
        scale: auth.unlocking
            ? 1.012
            : 1.026 - root.revealProgress * 0.026

        Behavior on scale {
            NumberAnimation {
                duration: auth.unlocking ? 210 : 560
                easing.type: Easing.OutCubic
            }
        }
    }

    // Low-opacity atmosphere only. The wallpaper remains visually dominant.
    Rectangle {
        anchors.fill: parent
        z: -3
        color: Qt.rgba(0.02, 0.03, 0.05, auth.unlocking ? 0.075 : 0.105)

        Behavior on color {
            ColorAnimation { duration: 210 }
        }
    }

    Rectangle {
        anchors.fill: parent
        z: -2
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(0.02, 0.03, 0.05, 0.035) }
            GradientStop { position: 0.48; color: Qt.rgba(0.02, 0.03, 0.05, 0.000) }
            GradientStop { position: 1.00; color: Qt.rgba(0.015, 0.025, 0.045, 0.125) }
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

        Row {
            anchors.top: parent.top
            anchors.topMargin: 24 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8 * root.uiScale

            MahoIcon {
                width: 15 * root.uiScale
                height: width
                icon: "lock"
                strokeColor: root.textSecondary
                lineWidth: 1.65
                anchors.verticalCenter: parent.verticalCenter
            }

            Text {
                text: "Screen locked"
                color: root.textSecondary
                font.pixelSize: 13 * root.uiScale
                font.weight: Font.Normal
                anchors.verticalCenter: parent.verticalCenter
            }
        }

        Row {
            anchors.top: parent.top
            anchors.topMargin: 22 * root.uiScale
            anchors.right: parent.right
            anchors.rightMargin: 27 * root.uiScale
            spacing: 14 * root.uiScale

            MahoIcon {
                width: 19 * root.uiScale
                height: width
                icon: "wifi"
                strokeColor: root.textPrimary
                lineWidth: 1.55
                visible: state.networkKind === "wifi"
                anchors.verticalCenter: parent.verticalCenter
            }

            Row {
                visible: state.batteryPercentageValid
                spacing: 5 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter

                MahoIcon {
                    width: 22 * root.uiScale
                    height: width
                    icon: "battery"
                    value: state.batteryFraction
                    strokeColor: root.textPrimary
                    lineWidth: 1.45
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    text: state.batteryPercentageValid
                        ? state.batteryPercentage + "%"
                        : ""
                    color: root.textPrimary
                    font.pixelSize: 13 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                spacing: 5 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter

                MahoIcon {
                    width: 18 * root.uiScale
                    height: width
                    icon: "keyboard"
                    strokeColor: root.textSecondary
                    lineWidth: 1.45
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    text: String(state.keyboardLayout || "US").toUpperCase()
                    color: root.textPrimary
                    font.pixelSize: 13 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        Item {
            id: mainContent
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(136 * root.uiScale, parent.height * 0.148)
            width: 580 * root.uiScale
            height: 680 * root.uiScale
            scale: auth.unlocking
                ? 1.009
                : 0.989 + root.revealProgress * 0.011

            Behavior on scale {
                NumberAnimation {
                    duration: auth.unlocking ? 190 : 440
                    easing.type: Easing.OutCubic
                }
            }

            Text {
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.currentTime
                color: root.textPrimary
                font.pixelSize: 108 * root.uiScale
                font.weight: Font.Light
                font.letterSpacing: -1.9 * root.uiScale
            }

            Text {
                anchors.top: parent.top
                anchors.topMargin: 166 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.currentDate
                color: root.textSecondary
                font.pixelSize: 18 * root.uiScale
                font.weight: Font.Normal
            }

            Text {
                anchors.top: parent.top
                anchors.topMargin: 258 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.greeting
                color: root.textPrimary
                font.pixelSize: 19 * root.uiScale
                font.weight: Font.Normal
            }

            Item {
                id: avatar
                anchors.top: parent.top
                anchors.topMargin: 304 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 92 * root.uiScale
                height: width

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: Qt.rgba(0, 0, 0, 0.09)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.10)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 4 * root.uiScale
                    radius: width / 2
                    color: theme.alpha(theme.accent, 0.82)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.20)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 8 * root.uiScale
                    radius: width / 2
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.07)
                }

                Text {
                    anchors.fill: parent
                    z: 5
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: state.displayName.length > 0
                        ? state.displayName.charAt(0).toUpperCase()
                        : "M"
                    color: Qt.rgba(1, 1, 1, 0.98)
                    font.pixelSize: 37 * root.uiScale
                    font.weight: Font.Light
                }
            }

            Item {
                id: authRegion
                anchors.top: parent.top
                anchors.topMargin: 438 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 442 * root.uiScale
                height: 174 * root.uiScale

                transform: Translate { id: shakeTranslate }

                SequentialAnimation {
                    id: shake
                    NumberAnimation { target: shakeTranslate; property: "x"; to: -7 * root.uiScale; duration: 45 }
                    NumberAnimation { target: shakeTranslate; property: "x"; to: 7 * root.uiScale; duration: 65 }
                    NumberAnimation { target: shakeTranslate; property: "x"; to: -4 * root.uiScale; duration: 55 }
                    NumberAnimation { target: shakeTranslate; property: "x"; to: 0; duration: 55 }
                }

                MahoGlassCapsuleV2 {
                    id: passwordShell
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    height: 60 * root.uiScale
                    theme: root.theme
                    focused: passwordInput.activeFocus

                    MahoIcon {
                        id: fieldLockGlyph
                        anchors.left: parent.left
                        anchors.leftMargin: 20 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        width: 18 * root.uiScale
                        height: width
                        icon: "lock"
                        strokeColor: root.textSecondary
                        lineWidth: 1.55
                    }

                    TextInput {
                        id: passwordInput
                        anchors.left: fieldLockGlyph.right
                        anchors.leftMargin: 12 * root.uiScale
                        anchors.right: eyeButton.left
                        anchors.rightMargin: 10 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        height: parent.height
                        verticalAlignment: TextInput.AlignVCenter
                        color: root.textPrimary
                        selectionColor: theme.alpha(theme.accent, 0.34)
                        selectedTextColor: root.textPrimary
                        font.pixelSize: 14 * root.uiScale
                        echoMode: root.passwordVisible
                            ? TextInput.Normal
                            : TextInput.Password
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
                            text: auth.authenticating
                                ? "Authenticating…"
                                : "Enter your password"
                            color: passwordInput.activeFocus
                                ? Qt.rgba(1, 1, 1, 0.66)
                                : root.textTertiary
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
                        anchors.rightMargin: 14 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        width: 36 * root.uiScale
                        height: 36 * root.uiScale

                        MahoIcon {
                            anchors.centerIn: parent
                            width: 19 * root.uiScale
                            height: width
                            icon: "eye"
                            strokeColor: root.textSecondary
                            lineWidth: 1.45
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
                }

                MahoGlassCapsuleV2 {
                    id: unlockButton
                    anchors.top: passwordShell.bottom
                    anchors.topMargin: 17 * root.uiScale
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 216 * root.uiScale
                    height: 52 * root.uiScale
                    theme: root.theme
                    strong: true
                    hovered: unlockHover.containsMouse
                    focused: unlockHover.containsMouse

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
                    font.weight: auth.errorText.length > 0
                        ? Font.Medium
                        : Font.Normal
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

        Item {
            id: sleepAction
            anchors.left: parent.left
            anchors.leftMargin: 28 * root.uiScale
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 27 * root.uiScale
            width: 118 * root.uiScale
            height: 42 * root.uiScale

            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 34 * root.uiScale
                height: width
                radius: width / 2
                color: sleepHover.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.115)
                    : Qt.rgba(1, 1, 1, 0.070)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.080)

                MahoIcon {
                    anchors.centerIn: parent
                    width: 17 * root.uiScale
                    height: width
                    icon: "power"
                    strokeColor: root.textPrimary
                    lineWidth: 1.65
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 45 * root.uiScale
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

        Item {
            id: switchUserAction
            anchors.right: parent.right
            anchors.rightMargin: 28 * root.uiScale
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 27 * root.uiScale
            width: 150 * root.uiScale
            height: 42 * root.uiScale
            visible: root.previewMode || state.switchUserCommand.length > 0

            Rectangle {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: 34 * root.uiScale
                height: width
                radius: width / 2
                color: switchHover.containsMouse
                    ? Qt.rgba(1, 1, 1, 0.115)
                    : Qt.rgba(1, 1, 1, 0.070)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.080)

                MahoIcon {
                    anchors.centerIn: parent
                    width: 18 * root.uiScale
                    height: width
                    icon: "users"
                    strokeColor: root.textPrimary
                    lineWidth: 1.55
                }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 45 * root.uiScale
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
