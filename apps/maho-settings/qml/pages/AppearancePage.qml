import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var palette
    readonly property var state: bridge && bridge.state.appearance ? bridge.state.appearance : ({})
    readonly property color foreground: palette ? palette.foreground : "#f3eef8"
    readonly property color muted: palette ? palette.muted : "#aaa3af"
    readonly property color accent: palette ? palette.accent : "#d0bcff"
    readonly property color surface: palette ? palette.surfaceElevated : "#2b2930"
    readonly property color borderColor: palette ? palette.border : "#3d3942"

    ScrollView {
        anchors.fill: parent
        clip: true

        ColumnLayout {
            width: Math.max(0, root.width - 14)
            spacing: 14

            PageHeader {
                title: "Appearance"
                subtitle: "Maho Settings requests changes through the existing Maho theme and compositor infrastructure."
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Appearance state unavailable"
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
                title: "Color mode"
                description: "Light and dark reuse the active wallpaper palette. Automatic is shown only when a real scheduling backend exists."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    spacing: 8

                    ChoicePill {
                        text: "Dark"
                        selected: root.state.mode === "dark"
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("appearance.mode", { mode: "dark" })
                    }
                    ChoicePill {
                        text: "Light"
                        selected: root.state.mode === "light"
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("appearance.mode", { mode: "light" })
                    }
                    ChoicePill {
                        text: "Automatic"
                        selected: root.state.mode === "automatic"
                        enabled: !!root.state.automaticSupported && !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                    }
                    Item { Layout.fillWidth: true }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Current wallpaper"
                description: "Palette integration follows the wallpaper owner; Settings does not replace it."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Text {
                    Layout.fillWidth: true
                    text: root.state.wallpaper && root.state.wallpaper.path
                        ? root.state.wallpaper.path
                        : "No authoritative wallpaper state is currently available."
                    color: root.state.wallpaper && root.state.wallpaper.path ? root.foreground : root.muted
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Comfort"
                description: "These are user preferences, not system-health or Guardian authority."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Reduce motion"
                        color: root.foreground
                        font.pixelSize: 13
                        Layout.fillWidth: true
                    }
                    MahoSwitch {
                        checked: !!root.state.reducedMotion
                        enabled: !!root.state.runtimeHooksAvailable && !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("appearance.reducedMotion", { enabled: checked })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Reduce transparency"
                        color: root.foreground
                        font.pixelSize: 13
                        Layout.fillWidth: true
                    }
                    MahoSwitch {
                        checked: !!root.state.reducedTransparency
                        enabled: !!root.state.runtimeHooksAvailable && !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("appearance.reducedTransparency", { enabled: checked })
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
