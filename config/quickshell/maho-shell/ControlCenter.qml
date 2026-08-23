import QtQuick

Item {
    id: center

    property var theme
    property var audio
    property var brightness
    property var system
    property var battery
    property var media
    property date now: new Date()

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
                onActivated: center.closeRequested()

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
                    Behavior on color { ColorAnimation { duration: 360 } }
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
                        Behavior on color { ColorAnimation { duration: 360 } }
                    }
                    Text {
                        width: parent.width
                        text: center.system && center.system.networkName !== ""
                            ? center.system.networkName : "Disconnected"
                        color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                        font.pixelSize: 8
                        elide: Text.ElideRight
                        Behavior on color { ColorAnimation { duration: 360 } }
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
                    Behavior on color { ColorAnimation { duration: 360 } }
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
                        Behavior on color { ColorAnimation { duration: 360 } }
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
                        Behavior on color { ColorAnimation { duration: 360 } }
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
                Behavior on color { ColorAnimation { duration: 360 } }
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 48
                anchors.verticalCenter: parent.verticalCenter
                text: center.battery && center.battery.charging ? "Charging" : "Battery"
                color: center.theme ? center.theme.foreground : "white"
                font.pixelSize: 10
                font.weight: Font.DemiBold
                Behavior on color { ColorAnimation { duration: 360 } }
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
                Behavior on color { ColorAnimation { duration: 360 } }
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
                Behavior on color { ColorAnimation { duration: 360 } }
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
                    Behavior on color { ColorAnimation { duration: 360 } }
                }
                Text {
                    text: "Maho dynamic palette"
                    color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                    font.pixelSize: 8
                    Behavior on color { ColorAnimation { duration: 360 } }
                }
            }

            Text {
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: "›"
                color: center.theme ? center.theme.muted : "white"
                font.pixelSize: 17
                Behavior on color { ColorAnimation { duration: 360 } }
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
                anchors.right: controls.left
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 1

                Text {
                    text: center.media && center.media.playing ? "NOW PLAYING" : "MEDIA"
                    color: center.theme ? center.theme.alpha(center.theme.primary, 0.82) : "white"
                    font.pixelSize: 8
                    font.weight: Font.DemiBold
                    Behavior on color { ColorAnimation { duration: 360 } }
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
                    Behavior on color { ColorAnimation { duration: 360 } }
                }
                Text {
                    width: parent.width
                    text: center.media ? center.media.artist : ""
                    color: center.theme ? center.theme.alpha(center.theme.muted, 0.68) : "#bdb8c3"
                    font.pixelSize: 8
                    elide: Text.ElideRight
                    Behavior on color { ColorAnimation { duration: 360 } }
                }
            }

            Row {
                id: controls
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6

                MahoCard {
                    width: 29; height: 29; radius: 14
                    theme: center.theme
                    interactive: center.media ? center.media.canPrevious : false
                    onActivated: center.mediaPreviousRequested()
                    Text { anchors.centerIn: parent; text: "󰒮"; color: center.theme ? center.theme.muted : "white"; font.family: "JetBrainsMono Nerd Font"; font.pixelSize: 14 }
                }
                MahoCard {
                    width: 31; height: 31; radius: 15
                    theme: center.theme
                    interactive: center.media ? center.media.canToggle : false
                    emphasized: true
                    onActivated: center.mediaToggleRequested()
                    Text { anchors.centerIn: parent; text: center.media && center.media.playing ? "󰏤" : "󰐊"; color: center.theme ? center.theme.foreground : "white"; font.family: "JetBrainsMono Nerd Font"; font.pixelSize: 14 }
                }
                MahoCard {
                    width: 29; height: 29; radius: 14
                    theme: center.theme
                    interactive: center.media ? center.media.canNext : false
                    onActivated: center.mediaNextRequested()
                    Text { anchors.centerIn: parent; text: "󰒭"; color: center.theme ? center.theme.muted : "white"; font.family: "JetBrainsMono Nerd Font"; font.pixelSize: 14 }
                }
            }
        }

        Row {
            width: parent.width
            height: 46
            spacing: 7

            Repeater {
                model: [
                    { "icon": "󰌾", "label": "Lock", "action": "lock" },
                    { "icon": "󰍹", "label": "Capture", "action": "capture" },
                    { "icon": "󰣇", "label": "Launcher", "action": "launcher" }
                ]

                delegate: MahoCard {
                    required property var modelData
                    width: (parent.width - 14) / 3
                    height: parent.height
                    theme: center.theme
                    interactive: true
                    onActivated: {
                        if (modelData.action === "lock") center.lockRequested()
                        else if (modelData.action === "capture") center.screenshotRequested()
                        else center.launcherRequested()
                    }

                    Column {
                        anchors.centerIn: parent
                        spacing: 1
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.icon
                            color: center.theme ? center.theme.primary : "white"
                            font.family: "JetBrainsMono Nerd Font"
                            font.pixelSize: 14
                            Behavior on color { ColorAnimation { duration: 360 } }
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: modelData.label
                            color: center.theme ? center.theme.muted : "white"
                            font.pixelSize: 8
                            Behavior on color { ColorAnimation { duration: 360 } }
                        }
                    }
                }
            }
        }
    }
}
