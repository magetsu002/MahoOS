pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    readonly property var pageState: bridge && bridge.state.power ? bridge.state.power : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function profileLabel(profile) {
        if (profile === "power-saver")
            return "Power Saver"
        if (!profile || profile.length === 0)
            return ""
        return profile.charAt(0).toUpperCase() + profile.slice(1)
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
                title: "Power"
                subtitle: "Battery state and performance preferences"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            SettingCard {
                visible: (root.pageState.batteries || []).length > 0
                title: "Battery"
                description: "Current battery state reported by the kernel"
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.batteries || []

                    MahoInsetRow {
                        required property var modelData
                        required property int index
                        title: modelData.model || modelData.name
                        description: modelData.health >= 0
                            ? modelData.health + "% health"
                            : ""
                        trailingText: modelData.capacity >= 0
                            ? modelData.capacity + "% · " + modelData.status
                            : modelData.status
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.batteries || []).length - 1
                    }
                }
            }

            AppearanceRow {
                visible: (root.pageState.batteries || []).length === 0
                title: "Battery"
                description: "No battery is currently reported by the kernel"
                iconName: "battery-missing"
                theme: theme
            }

            AppearanceRow {
                title: "Power mode"
                description: root.pageState.profileControlAvailable
                    ? "Choose the balance between performance and battery life"
                    : (root.pageState.profileError || "Power mode control is unavailable on this system")
                iconName: "battery"
                theme: theme

                RowLayout {
                    spacing: 6

                    Repeater {
                        model: root.pageState.profileControlAvailable ? (root.pageState.profiles || []) : []

                        ChoicePill {
                            required property string modelData
                            text: root.profileLabel(modelData)
                            selected: root.pageState.profile === modelData
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("power.profile", { profile: modelData })
                        }
                    }
                }
            }

            Text {
                visible: !!root.pageState.sessionPolicyError
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: root.pageState.sessionPolicyError || "No supported user-scoped session policy backend is available."
                color: theme.textFaint
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Text {
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: "Changing Power preferences here never triggers suspend, reboot, or shutdown."
                color: theme.textFaint
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
