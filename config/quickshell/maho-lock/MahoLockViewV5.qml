import QtQuick
import QtQuick.Effects

FocusScope {
    id: root

    required property var theme
    required property var lockState
    required property var auth
    property bool previewMode: false

    property real introProgress: 0
    property real errorPulse: 0
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
            return "Good night, " + root.lockState.displayName
        if (hour < 12)
            return "Good morning, " + root.lockState.displayName
        if (hour < 18)
            return "Good afternoon, " + root.lockState.displayName
        return "Good evening, " + root.lockState.displayName
    }

    readonly property color textPrimary: Qt.rgba(1, 1, 1, 0.97)
    readonly property color textSecondary: Qt.rgba(1, 1, 1, 0.74)
    readonly property color textTertiary: Qt.rgba(1, 1, 1, 0.54)

    focus: true

    function stage(start, finish) {
        const span = Math.max(0.001, finish - start)
        return Math.max(0, Math.min(1, (introProgress - start) / span))
    }

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
        introDelay.start()
        focusRecovery.restart()
    }

    Timer {
        id: introDelay
        interval: 50
        repeat: false
        onTriggered: root.introProgress = 1
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

    Behavior on introProgress {
        NumberAnimation {
            duration: 700
            easing.type: Easing.OutCubic
        }
    }

    SequentialAnimation {
        id: errorFlash
        NumberAnimation {
            target: root
            property: "errorPulse"
            from: 0
            to: 1
            duration: 85
            easing.type: Easing.OutCubic
        }
        NumberAnimation {
            target: root
            property: "errorPulse"
            to: 0
            duration: 460
            easing.type: Easing.OutCubic
        }
    }

    Rectangle {
        anchors.fill: parent
        z: -8
        color: theme.background
    }

    // User wallpaper authority. The selected local image is softened once for
    // the full lock surface so the controls can stay genuinely translucent.
    Image {
        id: wallpaperSource
        anchors.fill: parent
        z: -7
        source: root.lockState.lockWallpaperUrl
        asynchronous: true
        cache: true
        fillMode: Image.PreserveAspectCrop
        smooth: true
        mipmap: true
        sourceSize.width: root.width
        sourceSize.height: root.height
    }

    ShaderEffectSource {
        id: wallpaperTexture
        anchors.fill: parent
        z: -6
        sourceItem: wallpaperSource
        hideSource: true
        live: true
        recursive: false
    }

    MultiEffect {
        id: wallpaperEffect
        anchors.fill: parent
        z: -5
        source: wallpaperTexture
        visible: wallpaperSource.status === Image.Ready
        blurEnabled: true
        blur: 0.34
        blurMax: 32
        saturation: -0.025
        brightness: 0.018
        scale: auth.unlocking
            ? 1.010
            : 1.032 - root.stage(0.0, 0.78) * 0.032
        opacity: auth.unlocking ? 0.88 : 1

        Behavior on scale {
            NumberAnimation {
                duration: auth.unlocking ? 230 : 670
                easing.type: Easing.OutCubic
            }
        }

        Behavior on opacity {
            NumberAnimation { duration: 210; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        anchors.fill: parent
        z: -4
        color: Qt.rgba(0.012, 0.020, 0.040, auth.unlocking ? 0.055 : 0.095)

        Behavior on color {
            ColorAnimation { duration: 220; easing.type: Easing.OutCubic }
        }
    }

    Rectangle {
        anchors.fill: parent
        z: -3
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(0.02, 0.03, 0.05, 0.018) }
            GradientStop { position: 0.48; color: Qt.rgba(0.02, 0.03, 0.05, 0.000) }
            GradientStop { position: 1.00; color: Qt.rgba(0.01, 0.02, 0.04, 0.085) }
        }
    }

    Item {
        id: chrome
        anchors.fill: parent
        opacity: auth.unlocking ? 0 : 1

        Behavior on opacity {
            NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
        }

        Row {
            anchors.top: parent.top
            anchors.topMargin: 25 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 8 * root.uiScale
            opacity: root.stage(0.00, 0.45)
            transform: Translate {
                y: (1 - root.stage(0.00, 0.45)) * -7 * root.uiScale
            }

            MahoIconV2 {
                width: 15 * root.uiScale
                height: 15 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "lock"
                iconOpacity: 0.72
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
            anchors.rightMargin: 28 * root.uiScale
            spacing: 14 * root.uiScale
            opacity: root.stage(0.04, 0.50)
            transform: Translate {
                x: (1 - root.stage(0.04, 0.50)) * 8 * root.uiScale
            }

            MahoIconV2 {
                width: 19 * root.uiScale
                height: 19 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "wifi"
                iconOpacity: 0.90
                visible: root.lockState.networkKind === "wifi"
            }

            Row {
                visible: root.lockState.batteryAvailable
                spacing: 5 * root.uiScale

                MahoIconV2 {
                    width: 22 * root.uiScale
                    height: 22 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    name: "battery"
                    iconOpacity: 0.90
                }

                Text {
                    visible: root.lockState.batteryPercentageValid
                    text: root.lockState.batteryPercentageValid
                        ? root.lockState.batteryPercentage + "%"
                        : ""
                    color: root.textPrimary
                    font.pixelSize: 13 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            Row {
                spacing: 6 * root.uiScale

                MahoIconV2 {
                    width: 18 * root.uiScale
                    height: 18 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    name: "keyboard"
                    iconOpacity: 0.78
                }

                Text {
                    text: root.lockState.keyboardLayout
                    color: root.textPrimary
                    font.pixelSize: 13 * root.uiScale
                    font.capitalization: Font.AllUppercase
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }

        Item {
            id: mainContent
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.max(158 * root.uiScale, parent.height * 0.17)
            width: 580 * root.uiScale
            height: 700 * root.uiScale
            opacity: auth.unlocking ? 0 : root.stage(0.05, 0.88)

            transform: [
                Translate {
                    y: auth.unlocking
                        ? -10 * root.uiScale
                        : (1 - root.stage(0.05, 0.88)) * 18 * root.uiScale
                },
                Scale {
                    origin.x: mainContent.width / 2
                    origin.y: mainContent.height / 2
                    xScale: auth.unlocking
                        ? 1.012
                        : 0.985 + root.stage(0.05, 0.88) * 0.015
                    yScale: xScale
                }
            ]

            Behavior on opacity {
                NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
            }

            Text {
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.currentTime
                color: root.textPrimary
                font.pixelSize: 106 * root.uiScale
                font.weight: Font.Light
                font.letterSpacing: -1.8 * root.uiScale
                opacity: root.stage(0.04, 0.48)
            }

            Text {
                anchors.top: parent.top
                anchors.topMargin: 166 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.currentDate
                color: root.textSecondary
                font.pixelSize: 18 * root.uiScale
                opacity: root.stage(0.10, 0.56)
            }

            Text {
                anchors.top: parent.top
                anchors.topMargin: 267 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.greeting
                color: root.textPrimary
                font.pixelSize: 19 * root.uiScale
                font.weight: Font.Normal
                opacity: root.stage(0.17, 0.64)
            }

            Item {
                id: avatar
                anchors.top: parent.top
                anchors.topMargin: 322 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 112 * root.uiScale
                height: width
                opacity: root.stage(0.22, 0.72)
                scale: 0.88 + root.stage(0.22, 0.72) * 0.12

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: Qt.rgba(0, 0, 0, 0.10)
                    border.width: Math.max(1, root.uiScale)
                    border.color: Qt.rgba(1, 1, 1, 0.13)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 5 * root.uiScale
                    radius: width / 2
                    color: theme.alpha(
                        theme.mix(theme.accent, Qt.rgba(0.35, 0.45, 0.98, 1), 0.34),
                        0.88
                    )
                    border.width: Math.max(1, root.uiScale)
                    border.color: Qt.rgba(1, 1, 1, 0.23)
                }

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 10 * root.uiScale
                    radius: width / 2
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.075)
                }

                Text {
                    anchors.centerIn: parent
                    z: 5
                    text: root.lockState.displayName.length > 0
                        ? root.lockState.displayName.charAt(0).toUpperCase()
                        : "M"
                    color: Qt.rgba(1, 1, 1, 0.985)
                    font.pixelSize: 44 * root.uiScale
                    font.weight: Font.Light
                    renderType: Text.NativeRendering
                }
            }

            Item {
                id: authRegion
                anchors.top: parent.top
                anchors.topMargin: 456 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 444 * root.uiScale
                height: 186 * root.uiScale
                opacity: root.stage(0.28, 0.86)

                transform: Translate {
                    id: authTranslate
                    y: (1 - root.stage(0.28, 0.86)) * 14 * root.uiScale
                }

                SequentialAnimation {
                    id: shake
                    NumberAnimation { target: authTranslate; property: "x"; to: -7 * root.uiScale; duration: 45 }
                    NumberAnimation { target: authTranslate; property: "x"; to: 7 * root.uiScale; duration: 65 }
                    NumberAnimation { target: authTranslate; property: "x"; to: -4 * root.uiScale; duration: 55 }
                    NumberAnimation { target: authTranslate; property: "x"; to: 0; duration: 55 }
                }

                MahoGlassCapsuleV3 {
                    id: passwordShell
                    anchors.top: parent.top
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: parent.width
                    height: 62 * root.uiScale
                    theme: root.theme
                    focused: passwordInput.activeFocus
                    errorAmount: root.errorPulse

                    MahoIconV2 {
                        id: fieldLockIcon
                        anchors.left: parent.left
                        anchors.leftMargin: 21 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        width: 17 * root.uiScale
                        height: 17 * root.uiScale
                        name: "lock"
                        iconOpacity: passwordInput.activeFocus ? 0.90 : 0.67
                    }

                    TextInput {
                        id: passwordInput
                        anchors.left: fieldLockIcon.right
                        anchors.leftMargin: 13 * root.uiScale
                        anchors.right: eyeButton.left
                        anchors.rightMargin: 11 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        height: parent.height
                        verticalAlignment: TextInput.AlignVCenter
                        color: root.textPrimary
                        selectionColor: theme.alpha(theme.accent, 0.36)
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
                        anchors.rightMargin: 15 * root.uiScale
                        anchors.verticalCenter: parent.verticalCenter
                        width: 36 * root.uiScale
                        height: 36 * root.uiScale
                        scale: eyePointer.pressed ? 0.88 : (eyePointer.containsMouse ? 1.08 : 1)

                        Behavior on scale {
                            NumberAnimation { duration: 140; easing.type: Easing.OutCubic }
                        }

                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            color: eyePointer.pressed
                                ? Qt.rgba(1, 1, 1, 0.105)
                                : (eyePointer.containsMouse
                                    ? Qt.rgba(1, 1, 1, 0.065)
                                    : "transparent")

                            Behavior on color {
                                ColorAnimation { duration: 120; easing.type: Easing.OutCubic }
                            }
                        }

                        MahoIconV2 {
                            anchors.centerIn: parent
                            width: 19 * root.uiScale
                            height: 19 * root.uiScale
                            name: "eye"
                            iconOpacity: root.passwordVisible
                                ? 0
                                : (eyePointer.containsMouse ? 0.94 : 0.72)

                            Behavior on iconOpacity {
                                NumberAnimation { duration: 125; easing.type: Easing.OutCubic }
                            }
                        }

                        MahoIconV2 {
                            anchors.centerIn: parent
                            width: 19 * root.uiScale
                            height: 19 * root.uiScale
                            name: "eye-off"
                            iconOpacity: root.passwordVisible
                                ? (eyePointer.containsMouse ? 0.98 : 0.80)
                                : 0

                            Behavior on iconOpacity {
                                NumberAnimation { duration: 125; easing.type: Easing.OutCubic }
                            }
                        }

                        MouseArea {
                            id: eyePointer
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                root.passwordVisible = !root.passwordVisible
                                root.reclaimPasswordFocus()
                            }
                        }
                    }
                }

                MahoGlassCapsuleV3 {
                    id: unlockButton
                    anchors.top: passwordShell.bottom
                    anchors.topMargin: 17 * root.uiScale
                    anchors.horizontalCenter: parent.horizontalCenter
                    width: 216 * root.uiScale
                    height: 56 * root.uiScale
                    theme: root.theme
                    strong: true
                    hovered: unlockPointer.containsMouse
                    pressed: unlockPointer.pressed

                    Text {
                        anchors.centerIn: parent
                        text: auth.authenticating ? "Checking…" : "Unlock"
                        color: root.textPrimary
                        font.pixelSize: 14 * root.uiScale
                        font.weight: Font.DemiBold
                    }

                    MouseArea {
                        id: unlockPointer
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
                    opacity: 0.92
                }

                Connections {
                    target: auth

                    function onFailed() {
                        passwordInput.clear()
                        focusRecovery.attempts = 0
                        focusRecovery.restart()
                        shake.restart()
                        errorFlash.restart()
                    }
                }
            }
        }

        Item {
            id: actionLayer
            anchors.fill: parent
            opacity: auth.unlocking ? 0 : root.stage(0.42, 1.0)
            transform: Translate {
                y: (1 - root.stage(0.42, 1.0)) * 8 * root.uiScale
            }

            Behavior on opacity {
                NumberAnimation { duration: 180; easing.type: Easing.OutCubic }
            }

            MahoActionButton {
                anchors.left: parent.left
                anchors.leftMargin: 28 * root.uiScale
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 25 * root.uiScale
                theme: root.theme
                iconName: "power"
                label: "Sleep"
                enabled: true

                onTriggered: {
                    if (!root.previewMode)
                        sleepInvoke.restart()
                }
            }

            MahoActionButton {
                anchors.right: parent.right
                anchors.rightMargin: 28 * root.uiScale
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 25 * root.uiScale
                theme: root.theme
                iconName: "users"
                label: "Switch user"
                enabled: root.previewMode || root.lockState.switchUserCommand.length > 0
                visible: root.previewMode || root.lockState.switchUserCommand.length > 0

                onTriggered: {
                    if (!root.previewMode && root.lockState.switchUserCommand.length > 0)
                        switchInvoke.restart()
                }
            }
        }
    }

    Timer {
        id: sleepInvoke
        interval: 150
        repeat: false
        onTriggered: root.lockState.suspend()
    }

    Timer {
        id: switchInvoke
        interval: 150
        repeat: false
        onTriggered: root.lockState.switchUser()
    }
}
