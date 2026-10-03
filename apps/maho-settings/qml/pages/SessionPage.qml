pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.session ? bridge.state.session : ({})

    property bool editorOpen: false
    property string editorId: ""
    property string editorWhen: "start"

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function whenLabel(value) {
        if (value === "start")
            return "Login"
        if (value === "shutdown")
            return "Shutdown"
        if (value === "reload")
            return "Config reload"
        return value || "Session"
    }

    function openNew() {
        root.editorId = ""
        root.editorWhen = "start"
        commandField.text = ""
        workspaceField.text = ""
        root.editorOpen = true
    }

    function openEdit(row) {
        root.editorId = String(row.id || "")
        root.editorWhen = String(row.when || "start")
        commandField.text = String(row.command || "")
        workspaceField.text = String(row.workspace || "")
        root.editorOpen = true
    }

    function saveEditor() {
        root.bridge.perform("session.startupUpsert", {
            id: root.editorId,
            command: commandField.text.trim(),
            when: root.editorWhen,
            workspace: workspaceField.text.trim()
        })
    }

    Connections {
        target: root.bridge
        function onActionFinished(action, ok) {
            if (ok && String(action).startsWith("session."))
                root.editorOpen = false
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
                title: "Session"
                subtitle: "Startup and desktop session behavior"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Session configuration unavailable"
                detail: root.pageState.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            SettingCard {
                visible: !!root.pageState.available && !root.pageState.mutationAvailable
                title: "Editing unavailable in this runtime"
                description: "Session startup is still shown from the real configuration. Editing activates with the Maho user-overlay loader."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            SettingCard {
                visible: root.editorOpen
                title: root.editorId.length > 0 ? "Edit session command" : "New session command"
                description: "Managed commands are lifecycle-bound. Maho intentionally does not create commands that run on every unrelated config reload."
                surface: theme.surfaceElevated
                borderColor: theme.controlActiveRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoTextField {
                    id: commandField
                    Layout.fillWidth: true
                    placeholderText: "Command"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                MahoTextField {
                    id: workspaceField
                    Layout.fillWidth: true
                    placeholderText: "Workspace (optional)"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                MahoSegmentedControl {
                    Layout.preferredWidth: 250
                    theme: theme
                    options: [
                        { label: "Login", value: "start" },
                        { label: "Shutdown", value: "shutdown" }
                    ]
                    currentValue: root.editorWhen
                    onSelected: function(value) {
                        root.editorWhen = value
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }

                    MahoIconButton {
                        iconName: "close"
                        label: "Cancel"
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.editorOpen = false
                    }

                    MahoIconButton {
                        iconName: "check"
                        label: "Save session command"
                        emphasized: true
                        enabled: !root.bridge.actionBusy && commandField.text.trim().length > 0
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.saveEditor()
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Startup"
                description: "Commands observed in the current Maho session configuration."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoIconButton {
                    iconName: "add"
                    label: "Add session command"
                    emphasized: true
                    visible: !!root.pageState.canAddStartup
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.openNew()
                }

                Repeater {
                    model: root.pageState.startup || []

                    delegate: ManagedListRow {
                        id: startupRow
                        required property var modelData
                        required property int index
                        title: startupRow.modelData.command || "Session command"
                        description: startupRow.modelData.workspace
                            ? root.whenLabel(startupRow.modelData.when) + " · workspace " + startupRow.modelData.workspace
                            : root.whenLabel(startupRow.modelData.when)
                        trailingText: startupRow.modelData.userOwned ? "Maho" : "System"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.startup || []).length - 1

                        MahoIconButton {
                            visible: !!startupRow.modelData.canEdit
                            iconName: "edit"
                            label: "Edit session command"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openEdit(startupRow.modelData)
                        }

                        MahoIconButton {
                            visible: !!startupRow.modelData.canDelete
                            iconName: "delete"
                            label: "Delete session command"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("session.startupDelete", {
                                id: startupRow.modelData.id
                            })
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available && (root.pageState.variables || []).length > 0
                title: "Configuration variables"
                description: "Read-only variables observed while collecting the active Lua configuration."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.variables || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        required property int index
                        title: modelData.name || "Variable"
                        trailingText: String(modelData.value || "")
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.variables || []).length - 1
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available && (root.pageState.environment || []).length > 0
                title: "Environment"
                description: "Environment values declared by the active Hyprland configuration."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                Repeater {
                    model: root.pageState.environment || []
                    delegate: MahoInsetRow {
                        required property var modelData
                        required property int index
                        title: modelData.name || "Environment variable"
                        trailingText: String(modelData.value || "")
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.environment || []).length - 1
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
