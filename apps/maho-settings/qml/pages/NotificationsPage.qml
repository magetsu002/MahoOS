import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.notifications ? bridge.state.notifications : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        contentWidth: availableWidth
        ScrollBar.vertical: MahoScrollBar {
            foreground: theme.textPrimary
            reducedMotion: theme.reducedMotion
        }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Notifications"
                subtitle: "Control how MahoOS delivers and keeps notifications"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Maho Notify unavailable"
                detail: root.state.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Notifications"
                description: root.state.active
                    ? "Allow Maho Notify to deliver notifications"
                    : "Notification delivery is currently disabled"
                iconName: "preferences-system-notifications"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.state.active
                    enabled: !!root.state.globalEnableSupported && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) { root.bridge.perform("notification.enabled", { enabled: value }) }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Do Not Disturb"
                description: root.state.adaptiveQuiet
                    ? "Quiet mode is also being managed by Maho's current context policy"
                    : "Silence ordinary notifications until you turn it off"
                iconName: "notifications-disabled"
                theme: theme

                MahoSwitch {
                    reducedMotion: theme.reducedMotion
                    checked: !!root.state.dnd
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) { root.bridge.perform("notification.dnd", { enabled: value }) }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "Notification history"
                description: Number(root.state.historyCount || 0) + " retained · "
                    + Number(root.state.unreadCount || 0) + " unread"
                iconName: "view-history"
                theme: theme

                ChoicePill {
                    text: "Clear History"
                    enabled: !!root.state.historyClearSupported && !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.bridge.perform("notification.clearHistory", {})
                }
            }

            Text {
                visible: !!root.state.available
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: "Critical alert behavior and adaptive quiet remain owned by Maho Notify."
                color: theme.textFaint
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Text {
                visible: !!root.state.available
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: "Maho Notify does not currently expose notification sound, lock-screen visibility, or retention-duration preferences."
                color: theme.textFaint
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
