import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    property string targetRoute: "system"
    readonly property var state: bridge && bridge.state.system ? bridge.state.system : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

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

        ColumnLayout {
            width: Math.max(0, root.width - 14)
            spacing: 14

            PageHeader {
                title: "System"
                subtitle: "Truthful host and session information. Update, Recovery, Guardian and Storage remain separate authorities."
                foreground: root.foreground
                muted: root.muted
            }

            SettingCard {
                visible: root.deferredTitle().length > 0
                title: root.deferredTitle()
                description: "This route is reserved in the Settings architecture but its deep functionality is intentionally deferred from this milestone."
                surface: root.surface
                borderColor: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.32)
                foreground: root.foreground
                muted: root.muted

                Text {
                    Layout.fillWidth: true
                    text: "Maho Settings will present this owner when the corresponding V1 backend contract is ready; it will not duplicate the owner here."
                    color: root.muted
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }

            SettingCard {
                title: "About this system"
                description: "Read directly from OS, kernel, hardware and session sources."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                GridLayout {
                    columns: root.width < 760 ? 1 : 2
                    columnSpacing: 18
                    rowSpacing: 12
                    Layout.fillWidth: true

                    Repeater {
                        model: [
                            { label: "MahoOS version", value: root.state.mahoVersion || "Unknown" },
                            { label: "Source revision", value: root.state.sourceRevision || "Unknown" },
                            { label: "Host distribution", value: root.state.osName || "Unknown" },
                            { label: "Kernel", value: root.state.kernel || "Unknown" },
                            { label: "Architecture", value: root.state.architecture || "Unknown" },
                            { label: "Hostname", value: root.state.hostname || "Unknown" },
                            { label: "Processor", value: root.state.cpu || "Unknown" },
                            { label: "Memory", value: root.state.memory || "Unknown" },
                            { label: "Session", value: root.state.sessionType || root.state.desktop || "Unknown" },
                            { label: "Hyprland", value: root.state.hyprland && root.state.hyprland.version
                                ? root.state.hyprland.version
                                : "Unavailable" }
                        ]

                        ColumnLayout {
                            required property var modelData
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                text: modelData.label
                                color: root.muted
                                font.pixelSize: 10
                            }
                            Text {
                                text: modelData.value
                                color: root.foreground
                                font.pixelSize: 13
                                wrapMode: Text.WordWrap
                                Layout.fillWidth: true
                            }
                        }
                    }
                }
            }

            SettingCard {
                title: "Deferred V1 pages"
                description: "The remaining bounded routes stay explicit without pretending their deeper backends are implemented."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

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
                            color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.055)
                            border.width: 1
                            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07)

                            Text {
                                id: label
                                anchors.centerIn: parent
                                text: modelData
                                color: root.muted
                                font.pixelSize: 10
                            }
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
