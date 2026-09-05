import QtQuick
import Quickshell

Item {
    id: center

    property var theme
    property var audio
    property var brightness
    property var system
    property var battery
    property var media
    property var notifyStatus
    property date now: new Date()
    property bool powerExpanded: false
    readonly property real quickActionsTop: panelColumn.y + quickActions.y

    signal closeRequested()
    signal wifiRequested()
    signal bluetoothRequested()
    signal wallpaperRequested()
    signal lockRequested()
    signal screenshotRequested()
    signal launcherRequested()
    signal mediaPreviousRequested()
    signal mediaToggleRequested()
    signal mediaNextRequested()
    signal notificationsRequested()
    signal volumeRequested(real value)
    signal brightnessRequested(real value)

    implicitHeight: panelColumn.implicitHeight + 34

    function networkGlyph() {
        if (system && system.networkKind === "wifi") return "󰖩"
        if (system && system.networkKind === "ethernet") return "󰈀"
        return "󰖪"
    }

    function batteryGlyph() {
        if (battery && battery.charging) return "󰂄"
        const value = battery ? battery.percentage : 100
        if (value >= 90) return "󰁹"
        if (value >= 70) return "󰂀"
        if (value >= 50) return "󰁾"
        if (value >= 30) return "󰁼"
        return "󰁺"
    }

    function volumeGlyph() {
        if (audio && audio.muted) return "󰖁"
        const value = audio ? audio.volume : 0
        if (value < 30) return ""
        if (value < 70) return ""
        return ""
    }

    function runPowerAction(action) {
        powerExpanded = false
        Quickshell.execDetached([
            Quickshell.env("HOME") + "/.local/bin/maho-power",
            "action",
            action
        ])
    }

    component BottomAction: MahoCard {
        id: quick
        required property string iconText
        required property string labelText
        property bool activeState: false
        signal triggered()

        interactive: true
        emphasized: activeState
        onActivated: triggered()

        Column {
            anchors.centerIn: parent
            spacing: 1

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: quick.iconText
                color: center.theme ? center.theme.primary : "white"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 14
                textFormat: Text.PlainText
                Behavior on color { ColorAnimation { duration: 300 } }
            }

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: quick.labelText
                color: quick.activeState && center.theme
                    ? center.theme.alpha(center.theme.primary, 0.92)
                    : (center.theme ? center.theme.muted : "white")
                font.pixelSize: 8
                textFormat: Text.PlainText
                Behavior on color { ColorAnimation { duration: 300 } }
            }
        }
    }

    Column {
        id: panelColumn
        anchors.top: parent.top
        anchors.topMargin: 17
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 7

        Item {
            width: parent.width
            height: 39

            Column {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0

                Text {
                    text: Qt.formatDateTime(center.now, "HH:mm")
                    color: center.theme ? center.theme.foreground : "white"
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    Behavior on color { ColorAnimation { duration: 360 } }
                }

                Text {
                    text: Qt.formatDateTime(center.now, "ddd, MMM d")
                    color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                    font.pixelSize: 9
                    Behavior on color { ColorAnimation { duration: 360 } }
                }
            }

            MahoCard {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 31
                height: 31
                radius: 10
                theme: center.theme
                interactive: true
                onActivated: {
                    center.powerExpanded = false
                    center.closeRequested()
                }

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: center.theme ? center.theme.muted : "white"
                    font.pixelSize: 18
                    Behavior on color { ColorAnimation { duration: 300 } }
                }
            }
        }

        Row {
            width: parent.width
            height: 58
            spacing: 7

            MahoCard {
                width: (parent.width - parent.spacing) / 2
                height: parent.height
                theme: center.theme
                interactive: true
                onActivated: center.wifiRequested()

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 13
                    anchors.verticalCenter: parent.verticalCenter
                    text: center.networkGlyph()
                    color: center.theme
                        ? (center.system && center.system.networkKind === "none"
                            ? center.theme.error : center.theme.primary)
                        : "white"
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 17
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 45
                    anchors.right: parent.right
                    anchors.rightMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 0

                    Text {
                        text: "Wi-Fi"
                        color: center.theme ? center.theme.foreground : "white"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }

                    Text {
                        width: parent.width
                        text: center.system && center.system.networkName !== ""
                            ? center.system.networkName : "Disconnected"
                        color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                        font.pixelSize: 8
                        elide: Text.ElideRight
                    }
                }
            }

            MahoCard {
                width: (parent.width - parent.spacing) / 2
                height: parent.height
                theme: center.theme
                interactive: true
                onActivated: center.bluetoothRequested()

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 13
                    anchors.verticalCenter: parent.verticalCenter
                    text: center.system && center.system.bluetoothPowered ? "󰂯" : "󰂲"
                    color: center.theme
                        ? (center.system && center.system.bluetoothPowered
                            ? center.theme.primary : center.theme.alpha(center.theme.muted, 0.42))
                        : "white"
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 17
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 45
                    anchors.right: parent.right
                    anchors.rightMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 0

                    Text {
                        text: "Bluetooth"
                        color: center.theme ? center.theme.foreground : "white"
                        font.pixelSize: 10
                        font.weight: Font.DemiBold
                    }

                    Text {
                        width: parent.width
                        text: !center.system || !center.system.bluetoothAvailable
                            ? "Unavailable"
                            : (center.system.bluetoothConnected ? "Connected"
                                : (center.system.bluetoothPowered ? "On" : "Off"))
                        color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                        font.pixelSize: 8
                        elide: Text.ElideRight
                    }
                }
            }
        }

        MahoCard {
            width: parent.width
            height: 44
            visible: center.battery ? center.battery.available : false
            theme: center.theme

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: center.batteryGlyph()
                color: center.theme
                    ? (center.battery && center.battery.percentage <= 15 ? center.theme.error
                        : (center.battery && center.battery.charging ? center.theme.primary : center.theme.secondary))
                    : "white"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 16
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 48
                anchors.verticalCenter: parent.verticalCenter
                text: center.battery && center.battery.charging ? "Charging" : "Battery"
                color: center.theme ? center.theme.foreground : "white"
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: (center.battery ? center.battery.percentage : 100) + "%"
                color: center.theme
                    ? (center.battery && center.battery.percentage <= 15 ? center.theme.error : center.theme.muted)
                    : "white"
                font.pixelSize: 10
                font.weight: Font.DemiBold
            }
        }

        MahoCard {
            width: parent.width
            height: 48
            theme: center.theme
            interactive: true
            emphasized: center.notifyStatus && center.notifyStatus.unreadCount > 0
            onActivated: center.notificationsRequested()

            Rectangle {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: 27
                height: 27
                radius: 9
                color: center.theme
                    ? center.theme.alpha(center.theme.primary,
                        center.notifyStatus && center.notifyStatus.unreadCount > 0 ? 0.17 : 0.08)
                    : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: center.notifyStatus && center.notifyStatus.dndEnabled ? "󰂛" : "󰂚"
                    color: center.theme
                        ? (center.notifyStatus && center.notifyStatus.unreadCount > 0
                            ? center.theme.primary : center.theme.muted)
                        : "white"
                    font.family: "JetBrainsMono Nerd Font"
                    font.pixelSize: 14
                    textFormat: Text.PlainText
                }
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 50
                anchors.right: notifyArrow.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0

                Text {
                    text: "Notifications"
                    color: center.theme ? center.theme.foreground : "white"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: !center.notifyStatus || !center.notifyStatus.active
                        ? "Open notification center"
                        : (center.notifyStatus.dndEnabled
                            ? "DND on · " + String(center.notifyStatus.unreadCount) + " unread"
                            : (center.notifyStatus.unreadCount > 0
                                ? String(center.notifyStatus.unreadCount) + " unread"
                                : "All clear · DND off"))
                    color: center.theme ? center.theme.alpha(center.theme.muted, 0.70) : "#bdb8c3"
                    font.pixelSize: 8
                    elide: Text.ElideRight
                }
            }

            Text {
                id: notifyArrow
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: center.theme ? center.theme.muted : "white"
                font.pixelSize: 17
            }
        }

        SliderCard {
            width: parent.width
            theme: center.theme
            iconText: center.volumeGlyph()
            titleText: "Volume"
            value: center.audio ? center.audio.volume : 0
            accent: center.theme ? center.theme.primary : "#d0bcff"
            onValueRequested: function(value) { center.volumeRequested(value) }
        }

        SliderCard {
            width: parent.width
            theme: center.theme
            iconText: "󰃠"
            titleText: "Brightness"
            value: center.brightness ? Math.max(0, center.brightness.value) : 0
            sliderEnabled: center.brightness ? center.brightness.available : false
            accent: center.theme ? center.theme.tertiary : "#efb8c8"
            onValueRequested: function(value) { center.brightnessRequested(value) }
        }

        MahoCard {
            width: parent.width
            height: 44
            theme: center.theme
            interactive: true
            emphasized: true
            onActivated: center.wallpaperRequested()

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: "󰸉"
                color: center.theme ? center.theme.primary : "white"
                font.family: "JetBrainsMono Nerd Font"
                font.pixelSize: 16
            }

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 48
                anchors.verticalCenter: parent.verticalCenter
                spacing: 0

                Text {
                    text: "Wallpaper"
                    color: center.theme ? center.theme.foreground : "white"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }

                Text {
                    text: "Maho dynamic palette"
                    color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                    font.pixelSize: 8
                }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: center.theme ? center.theme.muted : "white"
                font.pixelSize: 17
            }
        }

        MahoCard {
            width: parent.width
            height: 70
            visible: center.media && center.media.available
            theme: center.theme

            Column {
                anchors.left: parent.left
                anchors.leftMargin: 14
                anchors.right: mediaControls.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1

                Text {
                    text: center.media && center.media.playing ? "NOW PLAYING" : "MEDIA"
                    color: center.theme ? center.theme.alpha(center.theme.primary, 0.82) : "white"
                    font.pixelSize: 8
                    font.weight: Font.DemiBold
                }

                Text {
                    width: parent.width
                    text: center.media
                        ? (center.media.title !== "" ? center.media.title : center.media.identity)
                        : ""
                    color: center.theme ? center.theme.foreground : "white"
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }

                Text {
                    width: parent.width
                    text: center.media ? center.media.artist : ""
                    color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                    font.pixelSize: 8
                    elide: Text.ElideRight
                }
            }

            Row {
                id: mediaControls
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                MahoCard {
                    width: 29
                    height: 29
                    radius: 14
                    theme: center.theme
                    interactive: center.media ? center.media.canPrevious : false
                    onActivated: center.mediaPreviousRequested()
                    Text {
                        anchors.centerIn: parent
                        text: "󰒮"
                        color: center.theme ? center.theme.muted : "white"
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 14
                    }
                }

                MahoCard {
                    width: 31
                    height: 31
                    radius: 15
                    theme: center.theme
                    interactive: center.media ? center.media.canToggle : false
                    emphasized: true
                    onActivated: center.mediaToggleRequested()
                    Text {
                        anchors.centerIn: parent
                        text: center.media && center.media.playing ? "󰏤" : "󰐊"
                        color: center.theme ? center.theme.foreground : "white"
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 14
                    }
                }

                MahoCard {
                    width: 29
                    height: 29
                    radius: 14
                    theme: center.theme
                    interactive: center.media ? center.media.canNext : false
                    onActivated: center.mediaNextRequested()
                    Text {
                        anchors.centerIn: parent
                        text: "󰒭"
                        color: center.theme ? center.theme.muted : "white"
                        font.family: "JetBrainsMono Nerd Font"
                        font.pixelSize: 14
                    }
                }
            }
        }

        Row {
            id: quickActions
            width: parent.width
            height: 46
            spacing: 7

            BottomAction {
                width: (parent.width - 14) / 3
                height: parent.height
                theme: center.theme
                iconText: "󰐥"
                labelText: "Power"
                activeState: center.powerExpanded
                onTriggered: center.powerExpanded = !center.powerExpanded
            }

            BottomAction {
                width: (parent.width - 14) / 3
                height: parent.height
                theme: center.theme
                iconText: "󰍹"
                labelText: "Capture"
                onTriggered: center.screenshotRequested()
            }

            BottomAction {
                width: (parent.width - 14) / 3
                height: parent.height
                theme: center.theme
                iconText: "󰣇"
                labelText: "Launcher"
                onTriggered: center.launcherRequested()
            }
        }
    }

    Rectangle {
        id: powerScrim
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: Math.max(0, center.quickActionsTop - 2)
        color: center.theme ? center.theme.alpha(center.theme.background, 0.16) : Qt.rgba(0, 0, 0, 0.15)
        opacity: center.powerExpanded ? 1 : 0
        visible: opacity > 0.001 || center.powerExpanded
        z: 30

        Behavior on opacity {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        TapHandler {
            enabled: center.powerExpanded
            onTapped: center.powerExpanded = false
        }
    }

    Item {
        id: powerDropdown
        anchors.left: parent.left
        anchors.right: parent.right
        y: center.quickActionsTop - height - 7
        height: compactPower.implicitHeight
        visible: opacity > 0.001 || center.powerExpanded
        opacity: center.powerExpanded ? 1 : 0
        scale: center.powerExpanded ? 1 : 0.965
        transformOrigin: Item.BottomLeft
        z: 40
        clip: false

        Behavior on opacity {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }

        Behavior on scale {
            NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
        }

        MahoPowerView {
            id: compactPower
            anchors.fill: parent
            theme: center.theme
            compact: true
            keyboardNavigation: false
            closeButtonVisible: true

            onCloseRequested: center.powerExpanded = false
            onActionRequested: function(action) { center.runPowerAction(action) }
        }

        Rectangle {
            id: powerPointer
            anchors.top: compactPower.bottom
            anchors.topMargin: -7
            x: (((powerDropdown.width - 14) / 3) - width) / 2
            width: 14
            height: 14
            rotation: 45
            color: center.theme
                ? center.theme.alpha(center.theme.surfaceHigh, 0.98)
                : Qt.rgba(0.16, 0.17, 0.23, 0.98)
            border.width: 0
            z: 1
        }
    }
}
