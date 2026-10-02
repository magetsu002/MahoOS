import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.notifications ? bridge.state.notifications : ({})
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
                title: "Notifications"
                subtitle: "Control notification behavior and history"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Maho Notify unavailable"
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
                title: "Delivery"
                description: root.state.active ? "Maho Notify is active." : "Maho Notify is currently inactive."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Notifications enabled"
                        color: root.foreground
                        font.pixelSize: 13
                        Layout.fillWidth: true
                    }
                    MahoSwitch {
                        checked: !!root.state.active
                        enabled: !!root.state.globalEnableSupported && !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("notification.enabled", { enabled: checked })
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "Do Not Disturb"
                        color: root.foreground
                        font.pixelSize: 13
                        Layout.fillWidth: true
                    }
                    MahoSwitch {
                        checked: !!root.state.dnd
                        enabled: !root.bridge.actionBusy
                        accent: root.accent
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("notification.dnd", { enabled: checked })
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.state.adaptiveQuiet
                        ? "Adaptive quiet is currently active from the existing Maho context policy."
                        : "Critical-alert behavior and adaptive quiet remain owned by Maho Notify."
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "History"
                description: Number(root.state.historyCount || 0) + " retained · "
                    + Number(root.state.unreadCount || 0) + " unread"
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        text: "History retention follows Maho Notify's existing bounded policy."
                        color: root.muted
                        font.pixelSize: 11
                        wrapMode: Text.WordWrap
                        Layout.fillWidth: true
                    }
                    ChoicePill {
                        text: "Clear History"
                        enabled: !!root.state.historyClearSupported && !root.bridge.actionBusy
                        accent: root.accent
                        surface: root.surface
                        foreground: root.foreground
                        muted: root.muted
                        onClicked: root.bridge.perform("notification.clearHistory", {})
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Capability boundary"
                description: "Maho Notify supports bounded runtime enable/disable and DND. It does not currently expose notification sound, lock-screen visibility, or retention-duration preferences."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Text {
                    Layout.fillWidth: true
                    text: "Settings leaves those controls absent instead of creating a second notification policy store."
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
