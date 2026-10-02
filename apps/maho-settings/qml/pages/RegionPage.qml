import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.region ? bridge.state.region : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    function stringIndex(rows, value) {
        if (!rows)
            return -1
        return Math.max(-1, rows.indexOf(value))
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar {
            foreground: root.foreground
        }

        ColumnLayout {
            width: Math.max(0, root.width - 14)
            spacing: 14

            PageHeader {
                title: "Region & Time"
                subtitle: "Language, keyboard layout, time and timezone"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Region and time state unavailable"
                detail: root.state.error || root.bridge.error
                retryVisible: true
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted
                accent: root.accent
                onRetryRequested: root.bridge.refresh()
            }

            SettingCard {
                visible: !!root.state.available
                title: "Time"
                description: root.state.timeSynchronized ? "Clock synchronized" : "Clock synchronization is not currently confirmed"
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                ColumnLayout {
                    Layout.fillWidth: true
                    Text { text: "Time zone"; color: root.muted; font.pixelSize: 11 }
                    MahoComboBox {
                        Layout.fillWidth: true
                        model: root.state.timezones || []
                        currentIndex: root.stringIndex(model, root.state.timezone || "")
                        enabled: !!root.state.timezoneControlAvailable && !root.bridge.actionBusy
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        accent: root.accent
                        onActivated: {
                            if (index >= 0)
                                root.bridge.perform("region.timezone", { timezone: model[index] })
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text { text: "Set time automatically"; color: root.foreground; font.pixelSize: 13; Layout.fillWidth: true }
                    MahoSwitch {
                        reducedMotion: root.bridge && root.bridge.state.appearance ? !!root.bridge.state.appearance.reducedMotion : false
                        checked: !!root.state.automaticTime
                        enabled: !!root.state.automaticTimeControlAvailable && !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("region.automaticTime", { enabled: checked })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Regional format"
                description: "System locale is delegated to systemd-localed and may require normal policy authentication."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    Layout.fillWidth: true
                    model: root.state.locales || []
                    currentIndex: root.stringIndex(model, root.state.locale || "")
                    enabled: !!root.state.localeControlAvailable && !root.bridge.actionBusy
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    onActivated: {
                        if (index >= 0)
                            root.bridge.perform("region.locale", { locale: model[index] })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Keyboard layout"
                description: "This entry point changes Hyprland's active XKB layout and persists it through the existing Settings session apply path."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    Layout.fillWidth: true
                    model: root.state.keyboardLayouts || []
                    currentIndex: root.stringIndex(model, root.state.keyboardLayout || "")
                    enabled: !!root.state.keyboardLayoutControlAvailable && !root.bridge.actionBusy
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    onActivated: {
                        if (index >= 0)
                            root.bridge.perform("region.keyboardLayout", { layout: model[index] })
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
