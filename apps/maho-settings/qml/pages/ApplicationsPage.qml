import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.applications ? bridge.state.applications : ({})
    readonly property color foreground: themePalette ? themePalette.foreground : "#f3eef8"
    readonly property color muted: themePalette ? themePalette.muted : "#aaa3af"
    readonly property color accent: themePalette ? themePalette.accent : "#d0bcff"
    readonly property color surface: themePalette ? themePalette.surfaceElevated : "#2b2930"
    readonly property color borderColor: themePalette ? themePalette.border : "#3d3942"

    function candidateIndex(rows, desktopId) {
        if (!rows)
            return -1
        for (let i = 0; i < rows.length; ++i)
            if (rows[i].id === desktopId)
                return i
        return -1
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
                title: "Applications"
                subtitle: "Choose default apps and review session applications"
                foreground: root.foreground
                muted: root.muted
            }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Application defaults unavailable"
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
                title: "Default browser"
                description: root.state.browser || "No browser default is currently registered."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    Layout.fillWidth: true
                    model: root.state.browserCandidates || []
                    textRole: "name"
                    currentIndex: root.candidateIndex(model, root.state.browser || "")
                    enabled: count > 0 && !root.bridge.actionBusy
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    onActivated: {
                        const row = root.state.browserCandidates[index]
                        if (row)
                            root.bridge.perform("applications.default", { kind: "browser", desktopId: row.id })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "File manager"
                description: root.state.fileManager || "No directory handler is currently registered."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                MahoComboBox {
                    Layout.fillWidth: true
                    model: root.state.fileManagerCandidates || []
                    textRole: "name"
                    currentIndex: root.candidateIndex(model, root.state.fileManager || "")
                    enabled: count > 0 && !root.bridge.actionBusy
                    surface: root.surface
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    onActivated: {
                        const row = root.state.fileManagerCandidates[index]
                        if (row)
                            root.bridge.perform("applications.default", { kind: "fileManager", desktopId: row.id })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Default associations"
                description: "Common MIME and link handlers use the same XDG MIME authority as other desktop applications."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.mimeAssociations || []

                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 5

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1

                                Text {
                                    text: modelData.label
                                    color: root.foreground
                                    font.pixelSize: 12
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                                Text {
                                    text: modelData.mime
                                    color: root.muted
                                    font.pixelSize: 9
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                            }

                            MahoComboBox {
                                Layout.preferredWidth: Math.min(270, Math.max(180, root.width * 0.34))
                                model: modelData.candidates || []
                                textRole: "name"
                                currentIndex: root.candidateIndex(model, modelData.default || "")
                                enabled: count > 0 && !root.bridge.actionBusy
                                surface: root.surface
                                foreground: root.foreground
                                muted: root.muted
                                accent: root.accent
                                onActivated: {
                                    const row = modelData.candidates[index]
                                    if (row)
                                        root.bridge.perform("applications.mimeDefault", {
                                            mime: modelData.mime,
                                            desktopId: row.id
                                        })
                                }
                            }
                        }
                    }
                }

                Text {
                    visible: (root.state.mimeAssociations || []).length === 0
                    text: "No common MIME associations are currently advertised by installed applications."
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            SettingCard {
                visible: !!root.state.available && (root.state.mimeAssociations || []).length > 0
                title: "Default associations"
                description: "Common MIME and link handlers managed through the XDG MIME authority."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.mimeAssociations || []

                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 5

                        Text {
                            text: modelData.label + " · " + modelData.mime
                            color: root.muted
                            font.pixelSize: 10
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }

                        MahoComboBox {
                            Layout.fillWidth: true
                            model: modelData.candidates || []
                            textRole: "name"
                            currentIndex: root.candidateIndex(model, modelData.default || "")
                            enabled: count > 0 && !root.bridge.actionBusy
                            surface: root.surface
                            foreground: root.foreground
                            muted: root.muted
                            accent: root.accent
                            onActivated: {
                                const row = modelData.candidates[index]
                                if (row)
                                    root.bridge.perform("applications.mimeDefault", {
                                        mime: modelData.mime,
                                        desktopId: row.id
                                    })
                            }
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Terminal"
                description: root.state.terminalError || "No supported terminal-default authority is available."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Text {
                    Layout.fillWidth: true
                    text: "Settings does not invent a private default-terminal registry when xdg-terminal-exec is unavailable."
                    color: root.muted
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Autostart"
                description: "Effective XDG session entries. This milestone keeps the list read-only rather than rewriting unrelated desktop files."
                surface: root.surface
                borderColor: root.borderColor
                foreground: root.foreground
                muted: root.muted

                Repeater {
                    model: root.state.autostart || []

                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 10
                        Text {
                            text: modelData.name
                            color: root.foreground
                            font.pixelSize: 12
                            Layout.fillWidth: true
                            elide: Text.ElideRight
                        }
                        Text {
                            text: (modelData.enabled ? "Enabled" : "Disabled") + " · " + modelData.source
                            color: root.muted
                            font.pixelSize: 10
                        }
                    }
                }

                Text {
                    visible: (root.state.autostart || []).length === 0
                    text: "No effective XDG autostart entries were found."
                    color: root.muted
                    font.pixelSize: 11
                }
            }

            Item { Layout.preferredHeight: 6 }
        }
    }
}
