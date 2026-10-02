import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    property string targetRoute: "system"
    readonly property var pageState: bridge && bridge.state.system ? bridge.state.system : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function deferredTitle() {
        switch (targetRoute) {
        case "updates": return "Updates"
        case "recovery": return "Recovery"
        case "guardian": return "Guardian"
        case "storage": return "Storage"
        default: return ""
        }
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
                title: "About"
                subtitle: "MahoOS, hardware and session information"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: root.deferredTitle().length > 0
                title: root.deferredTitle() + " is not available yet"
                detail: "This route is reserved for its real MahoOS owner. Settings will not duplicate or imitate that authority before the backend contract is ready."
                surface: theme.surfaceElevated
                borderColor: theme.controlActiveRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
            }

            AppearanceRow {
                title: "MahoOS"
                description: root.pageState.mahoVersion || "Version information unavailable"
                iconName: "computer"
                theme: theme

                Text {
                    text: root.pageState.sourceRevision
                        ? String(root.pageState.sourceRevision).slice(0, 10)
                        : ""
                    color: theme.textFaint
                    font.pixelSize: 11
                    font.family: "monospace"
                }
            }

            SettingCard {
                title: "System information"
                description: "Read directly from the operating system and current session"
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: [
                        { label: "System", value: root.pageState.osName || "Unknown" },
                        { label: "Kernel", value: root.pageState.kernel || "Unknown" },
                        { label: "Architecture", value: root.pageState.architecture || "Unknown" },
                        { label: "Hostname", value: root.pageState.hostname || "Unknown" },
                        { label: "Processor", value: root.pageState.cpu || "Unknown" },
                        { label: "Memory", value: root.pageState.memory || "Unknown" },
                        { label: "Session", value: root.pageState.sessionType || root.pageState.desktop || "Unknown" },
                        { label: "Hyprland", value: root.pageState.hyprland && root.pageState.hyprland.version
                            ? root.pageState.hyprland.version : "Unavailable" }
                    ]

                    MahoInsetRow {
                        required property var modelData
                        required property int index
                        title: modelData.label
                        trailingText: modelData.value
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < 7
                    }
                }
            }

            SettingCard {
                title: "Deferred V1 pages"
                description: "Reserved owners stay explicit without exposing fake controls"
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Flow {
                    Layout.fillWidth: true
                    spacing: 7

                    Repeater {
                        model: ["Network & Bluetooth", "Users", "Accessibility", "Updates", "Recovery", "Guardian", "Storage"]

                        Rectangle {
                            required property string modelData
                            width: label.implicitWidth + 20
                            height: 30
                            radius: 10
                            color: theme.controlFill
                            border.width: 1
                            border.color: theme.controlRim

                            Text {
                                id: label
                                anchors.centerIn: parent
                                text: modelData
                                color: theme.textSecondary
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
