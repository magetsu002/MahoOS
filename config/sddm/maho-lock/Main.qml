import QtQuick 2.15
import Qt5Compat.GraphicalEffects
import SddmComponents 2.0

FocusScope {
    id: root

    width: 1600
    height: 1000
    focus: true

    readonly property real uiScale: Math.max(0.78, Math.min(1.18,
        Math.min(width / 1600, height / 1000)))
    readonly property color textPrimary: Qt.rgba(0.973, 0.984, 1.0, 0.98)
    readonly property color textSecondary: Qt.rgba(0.957, 0.976, 1.0, 0.94)
    readonly property color textTertiary: Qt.rgba(0.933, 0.965, 1.0, 0.82)
    readonly property string uiFont: roundedFont.status === FontLoader.Ready
        ? "Nunito" : "Noto Sans"
    readonly property string loginUser: {
        const previous = String(userModel.lastUser || "")
        return previous.length > 0 ? previous : String(config.defaultUser || "")
    }
    readonly property string displayName: {
        const source = loginUser.replace(/[-_]+/g, " ").trim()
        return source.length > 0
            ? source.charAt(0).toUpperCase() + source.slice(1)
            : "User"
    }
    readonly property bool avatarAvailable:
        String(config.avatarAvailable || "false").toLowerCase() === "true"
    property int sessionIndex: Math.max(0, sessionModel.lastIndex)
    property bool passwordVisible: false
    property bool authenticating: false
    property string errorText: ""
    property date now: new Date()

    function submit() {
        if (passwordInput.text.length === 0 || authenticating)
            return
        authenticating = true
        errorText = ""
        sddm.login(loginUser, passwordInput.text, sessionIndex)
    }

    function reclaimFocus() {
        Qt.callLater(function() { passwordInput.forceActiveFocus() })
    }

    Component.onCompleted: reclaimFocus()

    Keys.onPressed: function(event) {
        if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
            submit()
            event.accepted = true
        } else if (event.key === Qt.Key_Escape) {
            passwordInput.clear()
            errorText = ""
            event.accepted = true
        }
    }

    Connections {
        target: sddm

        function onLoginFailed() {
            authenticating = false
            passwordInput.clear()
            errorText = "Incorrect password"
            failureAnimation.restart()
            reclaimFocus()
        }

        function onLoginSucceeded() {
            authenticating = true
            errorText = "Signing in…"
        }

        function onInformationMessage(message) {
            if (String(message || "").length > 0)
                errorText = String(message)
        }
    }

    Timer {
        interval: 1000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: root.now = new Date()
    }

    FontLoader {
        id: roundedFont
        source: "assets/Nunito-Variable.ttf"
    }

    Image {
        anchors.fill: parent
        source: config.background
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
        cache: true
        smooth: true
        mipmap: false
    }

    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(0.012, 0.020, 0.040, 0.095)
    }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(0.02, 0.03, 0.05, 0.018) }
            GradientStop { position: 0.48; color: Qt.rgba(0.02, 0.03, 0.05, 0.000) }
            GradientStop { position: 1.00; color: Qt.rgba(0.01, 0.02, 0.04, 0.085) }
        }
    }

    RadialGradient {
        anchors.fill: parent
        horizontalRadius: width * 0.38
        verticalRadius: height * 0.56
        verticalOffset: -height * 0.02
        gradient: Gradient {
            GradientStop { position: 0.00; color: Qt.rgba(0.025, 0.086, 0.190, 0.19) }
            GradientStop { position: 0.52; color: Qt.rgba(0.025, 0.086, 0.190, 0.085) }
            GradientStop { position: 0.78; color: Qt.rgba(0.031, 0.106, 0.227, 0.000) }
            GradientStop { position: 1.00; color: Qt.rgba(0.031, 0.106, 0.227, 0.000) }
        }
    }

    Row {
        anchors.top: parent.top
        anchors.topMargin: 35 * root.uiScale
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 8 * root.uiScale

        MahoSddmIcon {
            width: 16 * root.uiScale
            height: 16 * root.uiScale
            anchors.verticalCenter: parent.verticalCenter
            name: "lock"
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "Welcome to MahoOS"
            color: root.textSecondary
            font.pixelSize: 16 * root.uiScale
            font.family: root.uiFont
            font.weight: Font.DemiBold
            style: Text.Raised
            styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.26)
        }
    }

    Row {
        anchors.top: parent.top
        anchors.topMargin: 34 * root.uiScale
        anchors.right: parent.right
        anchors.rightMargin: 30 * root.uiScale
        spacing: 7 * root.uiScale

        MahoSddmIcon {
            width: 18 * root.uiScale
            height: 18 * root.uiScale
            anchors.verticalCenter: parent.verticalCenter
            name: "keyboard"
        }

        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "US"
            color: root.textPrimary
            font.pixelSize: 15 * root.uiScale
            font.family: root.uiFont
            font.weight: Font.DemiBold
        }
    }

    Item {
        id: mainContent
        anchors.horizontalCenter: parent.horizontalCenter
        y: Math.max(158 * root.uiScale, parent.height * 0.17)
        width: 580 * root.uiScale
        height: 700 * root.uiScale

        Text {
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(root.now, "HH:mm")
            color: root.textPrimary
            font.pixelSize: 122 * root.uiScale
            font.family: "Noto Sans"
            font.weight: Font.Light
            font.letterSpacing: -1.8 * root.uiScale
            renderType: Text.NativeRendering
            style: Text.Raised
            styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.11)
        }

        Text {
            anchors.top: parent.top
            anchors.topMargin: 166 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            text: Qt.formatDateTime(root.now, "dddd, d MMMM")
            color: root.textSecondary
            font.pixelSize: 22 * root.uiScale
            font.family: root.uiFont
            font.weight: Font.DemiBold
            style: Text.Raised
            styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.18)
        }

        Text {
            anchors.top: parent.top
            anchors.topMargin: 267 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            text: {
                const hour = root.now.getHours()
                if (hour < 5) return "Good night, " + root.displayName
                if (hour < 12) return "Good morning, " + root.displayName
                if (hour < 18) return "Good afternoon, " + root.displayName
                return "Good evening, " + root.displayName
            }
            color: root.textPrimary
            font.pixelSize: 23 * root.uiScale
            font.family: root.uiFont
            font.weight: Font.DemiBold
            style: Text.Raised
            styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.18)
        }

        Item {
            id: avatar
            anchors.top: parent.top
            anchors.topMargin: 310 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            width: 152 * root.uiScale
            height: width

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: Qt.rgba(0.490, 0.804, 1.000, 0.18)
                border.width: Math.max(1, root.uiScale)
                border.color: Qt.rgba(0.882, 0.961, 1.000, 0.76)
            }

            Rectangle {
                anchors.fill: parent
                anchors.margins: 5 * root.uiScale
                radius: width / 2
                color: Qt.rgba(0.28, 0.54, 0.90, 0.88)
                border.width: Math.max(1, root.uiScale)
                border.color: Qt.rgba(1, 1, 1, 0.23)
            }

            Text {
                anchors.fill: parent
                text: root.displayName.length > 0 ? root.displayName.charAt(0) : "M"
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: root.textPrimary
                font.pixelSize: 44 * root.uiScale
                font.family: root.uiFont
                font.weight: Font.Light
            }

            Image {
                id: avatarImage
                anchors.fill: parent
                anchors.margins: 5 * root.uiScale
                source: root.avatarAvailable ? config.avatar : ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: false
                cache: true
                smooth: true
                mipmap: true
                visible: false
            }

            Rectangle {
                id: avatarMask
                anchors.fill: avatarImage
                radius: width / 2
                color: "white"
                visible: false
            }

            OpacityMask {
                anchors.fill: avatarImage
                source: avatarImage
                maskSource: avatarMask
                visible: root.avatarAvailable && avatarImage.status === Image.Ready
            }

            Rectangle {
                anchors.fill: parent
                radius: width / 2
                color: "transparent"
                border.width: Math.max(1, root.uiScale)
                border.color: Qt.rgba(0.882, 0.961, 1.000, 0.70)
            }
        }

        Item {
            id: authRegion
            anchors.top: parent.top
            anchors.topMargin: 477 * root.uiScale
            anchors.horizontalCenter: parent.horizontalCenter
            width: 504 * root.uiScale
            height: 205 * root.uiScale

            transform: Translate { id: authTranslate }

            SequentialAnimation {
                id: failureAnimation
                NumberAnimation { target: authTranslate; property: "x"; to: -7 * root.uiScale; duration: 45 }
                NumberAnimation { target: authTranslate; property: "x"; to: 7 * root.uiScale; duration: 65 }
                NumberAnimation { target: authTranslate; property: "x"; to: -4 * root.uiScale; duration: 55 }
                NumberAnimation { target: authTranslate; property: "x"; to: 0; duration: 55 }
            }

            Rectangle {
                id: passwordShell
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width
                height: 74 * root.uiScale
                radius: height / 2
                color: passwordInput.activeFocus
                    ? Qt.rgba(0.804, 0.910, 1.000, 0.31)
                    : Qt.rgba(0.804, 0.910, 1.000, 0.24)
                border.width: Math.max(1, height / 60)
                border.color: passwordInput.activeFocus
                    ? Qt.rgba(0.882, 0.953, 1.000, 0.64)
                    : Qt.rgba(0.882, 0.953, 1.000, 0.46)

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: Math.max(1, root.uiScale)
                    radius: Math.max(0, parent.radius - 1)
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, passwordInput.activeFocus ? 0.15 : 0.10)
                }

                MahoSddmIcon {
                    id: fieldLockIcon
                    anchors.left: parent.left
                    anchors.leftMargin: 28 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    width: 18 * root.uiScale
                    height: 18 * root.uiScale
                    name: "lock"
                }

                Rectangle {
                    id: fieldDivider
                    anchors.left: fieldLockIcon.right
                    anchors.leftMargin: 16 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    width: Math.max(1, root.uiScale)
                    height: 30 * root.uiScale
                    color: Qt.rgba(0.92, 0.97, 1.00,
                        passwordInput.activeFocus ? 0.30 : 0.20)
                }

                TextInput {
                    id: passwordInput
                    anchors.left: fieldDivider.right
                    anchors.leftMargin: 17 * root.uiScale
                    anchors.right: eyeButton.left
                    anchors.rightMargin: 11 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    height: parent.height
                    verticalAlignment: TextInput.AlignVCenter
                    color: root.textPrimary
                    selectionColor: Qt.rgba(0.35, 0.60, 0.98, 0.36)
                    selectedTextColor: root.textPrimary
                    font.pixelSize: 16 * root.uiScale
                    font.family: root.uiFont
                    font.weight: Font.DemiBold
                    echoMode: root.passwordVisible ? TextInput.Normal : TextInput.Password
                    passwordCharacter: "●"
                    enabled: !root.authenticating
                    focus: true
                    activeFocusOnPress: true
                    selectByMouse: true
                    clip: true
                    inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText

                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        visible: passwordInput.text.length === 0
                        text: root.authenticating ? "Authenticating…" : "Enter your password"
                        color: passwordInput.activeFocus ? root.textSecondary : root.textTertiary
                        font.pixelSize: 16 * root.uiScale
                        font.family: root.uiFont
                        font.weight: Font.DemiBold
                        style: Text.Raised
                        styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.16)
                    }

                    Keys.onReturnPressed: root.submit()
                    Keys.onEnterPressed: root.submit()
                }

                Item {
                    id: eyeButton
                    anchors.right: parent.right
                    anchors.rightMargin: 15 * root.uiScale
                    anchors.verticalCenter: parent.verticalCenter
                    width: 36 * root.uiScale
                    height: 36 * root.uiScale

                    MahoSddmIcon {
                        anchors.centerIn: parent
                        width: 20 * root.uiScale
                        height: 20 * root.uiScale
                        name: "eye"
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.passwordVisible = !root.passwordVisible
                            root.reclaimFocus()
                        }
                    }
                }
            }

            Rectangle {
                id: loginButton
                anchors.top: passwordShell.bottom
                anchors.topMargin: 17 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                width: 232 * root.uiScale
                height: 60 * root.uiScale
                radius: height / 2
                color: loginPointer.pressed
                    ? Qt.rgba(0.804, 0.910, 1.000, 0.32)
                    : (loginPointer.containsMouse
                        ? Qt.rgba(0.804, 0.910, 1.000, 0.29)
                        : Qt.rgba(0.804, 0.910, 1.000, 0.26))
                border.width: Math.max(1, height / 60)
                border.color: Qt.rgba(0.882, 0.953, 1.000, 0.50)

                Rectangle {
                    anchors.fill: parent
                    anchors.margins: Math.max(1, root.uiScale)
                    radius: Math.max(0, parent.radius - 1)
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.10)
                }

                Text {
                    anchors.centerIn: parent
                    text: root.authenticating ? "Checking…" : "Log in"
                    color: root.textPrimary
                    font.pixelSize: 16 * root.uiScale
                    font.family: root.uiFont
                    font.weight: Font.Bold
                    style: Text.Raised
                    styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.16)
                }

                MouseArea {
                    id: loginPointer
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: !root.authenticating
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.submit()
                }
            }

            Text {
                anchors.top: loginButton.bottom
                anchors.topMargin: 12 * root.uiScale
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.errorText.length > 0 ? root.errorText : "Press Enter to log in"
                color: root.errorText.length > 0
                    ? Qt.rgba(1.0, 0.72, 0.76, 0.98)
                    : root.textSecondary
                font.pixelSize: 13 * root.uiScale
                font.family: root.uiFont
                font.weight: Font.DemiBold
                style: Text.Raised
                styleColor: Qt.rgba(0.020, 0.078, 0.176, 0.18)
            }
        }
    }

    Rectangle {
        id: sleepButton
        anchors.left: parent.left
        anchors.leftMargin: 36 * root.uiScale
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.uiScale
        width: 128 * root.uiScale
        height: 52 * root.uiScale
        radius: height / 2
        color: sleepPointer.containsMouse
            ? Qt.rgba(0.031, 0.106, 0.227, 0.26)
            : Qt.rgba(0.031, 0.106, 0.227, 0.20)
        border.width: 1
        border.color: Qt.rgba(0.90, 0.97, 1.0, 0.18)

        Row {
            anchors.centerIn: parent
            spacing: 14 * root.uiScale

            MahoSddmIcon {
                width: 20 * root.uiScale
                height: 20 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "power"
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Sleep"
                color: root.textPrimary
                font.pixelSize: 13 * root.uiScale
                font.family: root.uiFont
                font.weight: Font.DemiBold
            }
        }

        MouseArea {
            id: sleepPointer
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: sddm.suspend()
        }
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.uiScale
        width: 176 * root.uiScale
        height: 52 * root.uiScale
        radius: height / 2
        color: Qt.rgba(0.031, 0.106, 0.227, 0.23)
        border.width: 1
        border.color: Qt.rgba(0.90, 0.97, 1.0, 0.20)

        Row {
            anchors.centerIn: parent
            spacing: 9 * root.uiScale

            MahoSddmIcon {
                width: 18 * root.uiScale
                height: 18 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "session"
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Hyprland"
                color: root.textPrimary
                font.pixelSize: 13 * root.uiScale
                font.family: root.uiFont
                font.weight: Font.DemiBold
            }
        }
    }

    Rectangle {
        anchors.right: parent.right
        anchors.rightMargin: 36 * root.uiScale
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 30 * root.uiScale
        width: 128 * root.uiScale
        height: 52 * root.uiScale
        radius: height / 2
        color: restartPointer.containsMouse
            ? Qt.rgba(0.031, 0.106, 0.227, 0.26)
            : Qt.rgba(0.031, 0.106, 0.227, 0.20)
        border.width: 1
        border.color: Qt.rgba(0.90, 0.97, 1.0, 0.18)

        Row {
            anchors.centerIn: parent
            spacing: 14 * root.uiScale

            MahoSddmIcon {
                width: 20 * root.uiScale
                height: 20 * root.uiScale
                anchors.verticalCenter: parent.verticalCenter
                name: "restart"
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: "Restart"
                color: root.textPrimary
                font.pixelSize: 13 * root.uiScale
                font.family: root.uiFont
                font.weight: Font.DemiBold
            }
        }

        MouseArea {
            id: restartPointer
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: sddm.reboot()
        }
    }
}

