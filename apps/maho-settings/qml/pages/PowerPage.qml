import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.power ? bridge.state.power : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

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
                title: "Power"
                subtitle: "Battery, performance and power preferences"
                foreground: root.foreground
                muted: root.muted
            }

            SettingCard {
                title: "Battery"
                description: root.state.batteries && root.state.batteries.length > 0
                    ? "Kernel power-supply state"
                    : "No battery is reported by the kernel."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.batteries || []

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        Text {
                            text: modelData.model || modelData.name
                            color: root.foreground
                            font.pixelSize: 13
                            Layout.fillWidth: true
                        }
                        Text {
                            text: modelData.capacity >= 0
                                ? modelData.capacity + "% · " + modelData.status
                                : modelData.status
                            color: root.muted
                            font.pixelSize: 12
                        }
                        Text {
                            visible: modelData.health >= 0
                            text: modelData.health + "% health"
                            color: root.muted
                            font.pixelSize: 12
                        }
                    }
                }
            }

            SettingCard {
                title: "Power mode"
                description: root.state.profileControlAvailable
                    ? "Delegated to power-profiles-daemon."
                    : (root.state.profileError || "No supported power-profile backend is available.")
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    visible: !!root.state.profileControlAvailable
                    spacing: 8

                    Repeater {
                        model: root.state.profiles || []
                        ChoicePill {
                            required property string modelData
                            text: modelData === "power-saver" ? "Power Saver"
                                : modelData.charAt(0).toUpperCase() + modelData.slice(1)
                            selected: root.state.profile === modelData
                            enabled: !root.bridge.actionBusy
                            accent: root.accent
                            surface: root.surface
                            foreground: root.foreground
                            muted: root.muted
                            onClicked: root.bridge.perform("power.profile", { profile: modelData })
                        }
                    }
                    Item { Layout.fillWidth: true }
                }
            }

            SettingCard {
                title: "Screen, suspend & lid"
                description: root.state.sessionPolicyError || "No supported user-scoped session policy backend is available."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Text {
                    Layout.fillWidth: true
                    text: "These preferences stay absent until MahoOS has a bounded policy owner; changing Power settings here never triggers suspend, reboot, or shutdown."
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
