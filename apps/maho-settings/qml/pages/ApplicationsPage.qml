import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    readonly property var state: bridge && bridge.state.applications ? bridge.state.applications : ({})

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

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
        contentWidth: availableWidth
        ScrollBar.vertical: MahoScrollBar {
            foreground: theme.textPrimary
            reducedMotion: theme.reducedMotion
        }

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Applications"
                subtitle: "Choose default apps and review session startup"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.state.available && !root.bridge.loading
                title: "Application defaults unavailable"
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
                title: "Default browser"
                description: root.state.browser || "No browser default is currently registered"
                iconName: "applications-internet"
                theme: theme

                MahoComboBox {
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.browserCandidates || []
                    textRole: "name"
                    currentIndex: root.candidateIndex(model, root.state.browser || "")
                    enabled: count > 0 && !root.bridge.actionBusy
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: {
                        const row = root.state.browserCandidates[index]
                        if (row)
                            root.bridge.perform("applications.default", {
                                kind: "browser",
                                desktopId: row.id
                            })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.state.available
                title: "File manager"
                description: root.state.fileManager || "No directory handler is currently registered"
                iconName: "system-file-manager"
                theme: theme

                MahoComboBox {
                    Layout.preferredWidth: Math.min(340, Math.max(220, root.width * 0.40))
                    model: root.state.fileManagerCandidates || []
                    textRole: "name"
                    currentIndex: root.candidateIndex(model, root.state.fileManager || "")
                    enabled: count > 0 && !root.bridge.actionBusy
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                    onActivated: {
                        const row = root.state.fileManagerCandidates[index]
                        if (row)
                            root.bridge.perform("applications.default", {
                                kind: "fileManager",
                                desktopId: row.id
                            })
                    }
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Default associations"
                description: "Common handlers managed through the system XDG MIME authority"
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.state.mimeAssociations || []

                    ColumnLayout {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        spacing: 8

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 14

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2

                                Text {
                                    text: modelData.label
                                    color: theme.textPrimary
                                    font.pixelSize: 12
                                    font.weight: Font.Medium
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }

                                Text {
                                    text: modelData.mime
                                    color: theme.textFaint
                                    font.pixelSize: 10
                                    Layout.fillWidth: true
                                    elide: Text.ElideRight
                                }
                            }

                            MahoComboBox {
                                Layout.preferredWidth: Math.min(300, Math.max(190, root.width * 0.34))
                                model: modelData.candidates || []
                                textRole: "name"
                                currentIndex: root.candidateIndex(model, modelData.default || "")
                                enabled: count > 0 && !root.bridge.actionBusy
                                surface: theme.controlFill
                                foreground: theme.textPrimary
                                muted: theme.textSecondary
                                accent: theme.accent
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

                        Rectangle {
                            visible: index < (root.state.mimeAssociations || []).length - 1
                            Layout.fillWidth: true
                            height: 1
                            color: theme.divider
                        }
                    }
                }

                Text {
                    visible: (root.state.mimeAssociations || []).length === 0
                    Layout.fillWidth: true
                    text: "No common file or link handlers are currently advertised."
                    color: theme.textSecondary
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }
            }

            SettingCard {
                visible: !!root.state.available
                title: "Start at login"
                description: "Effective XDG session entries"
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.state.autostart || []

                    MahoInsetRow {
                        required property var modelData
                        required property int index
                        title: modelData.name
                        description: modelData.source
                        trailingText: modelData.enabled ? "Enabled" : "Disabled"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.state.autostart || []).length - 1
                    }
                }

                Text {
                    visible: (root.state.autostart || []).length === 0
                    Layout.fillWidth: true
                    text: "No effective startup entries were found."
                    color: theme.textSecondary
                    font.pixelSize: 11
                }
            }

            Text {
                visible: !!root.state.available && !!root.state.terminalError
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: root.state.terminalError
                color: theme.textFaint
                font.pixelSize: 11
                wrapMode: Text.WordWrap
            }

            Text {
                visible: !!root.state.available
                Layout.fillWidth: true
                Layout.leftMargin: 4
                Layout.rightMargin: 4
                text: "Application defaults remain owned by the XDG MIME authority. Settings does not invent a private default-terminal registry when the system has no supported terminal-default authority."
                color: theme.textFaint
                font.pixelSize: 10
                wrapMode: Text.WordWrap
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
