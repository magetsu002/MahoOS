pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.rules ? bridge.state.rules : ({})

    property bool editorOpen: false
    property string editorKind: "window"
    property string editorId: ""
    property var originalWorkspaceFields: null
    property string editorError: ""

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function objectText(value) {
        try {
            return JSON.stringify(value || {}, null, 2)
        } catch (error) {
            return "{}"
        }
    }

    function objectSummary(value) {
        if (!value || typeof value !== "object")
            return ""
        const keys = Object.keys(value)
        if (keys.length === 0)
            return "No fields"
        return keys.slice(0, 4).map(function(key) {
            return key + "=" + String(value[key])
        }).join(" · ") + (keys.length > 4 ? " · …" : "")
    }

    function parseObject(text, label) {
        try {
            const value = JSON.parse(text)
            if (!value || typeof value !== "object" || Array.isArray(value)) {
                root.editorError = label + " must be a JSON object."
                return null
            }
            if (Object.keys(value).length === 0) {
                root.editorError = label + " cannot be empty."
                return null
            }
            return value
        } catch (error) {
            root.editorError = label + " contains invalid JSON."
            return null
        }
    }

    function openNew(kind) {
        root.editorKind = kind
        root.editorId = ""
        root.originalWorkspaceFields = null
        root.editorError = ""
        nameField.text = ""
        matchArea.text = kind === "workspace"
            ? '{"workspace":"1"}'
            : '{"class":""}'
        effectsArea.text = kind === "workspace" ? "" : '{"float":true}'
        root.editorOpen = true
    }

    function openEdit(kind, row) {
        root.editorKind = kind
        root.editorId = String(row.id || "")
        root.editorError = ""
        if (kind === "workspace") {
            root.originalWorkspaceFields = row.fields
            nameField.text = ""
            matchArea.text = root.objectText(row.fields)
            effectsArea.text = ""
        } else {
            root.originalWorkspaceFields = null
            nameField.text = String(row.name || "")
            matchArea.text = root.objectText(row.match)
            effectsArea.text = root.objectText(row.effects)
        }
        root.editorOpen = true
    }

    function saveEditor() {
        root.editorError = ""
        if (root.editorKind === "workspace") {
            const fields = root.parseObject(matchArea.text, "Workspace fields")
            if (!fields)
                return
            root.bridge.perform("rules.workspaceUpsert", {
                fields: fields,
                originalFields: root.originalWorkspaceFields
            })
            return
        }

        const match = root.parseObject(matchArea.text, "Match")
        if (!match)
            return
        const effects = root.parseObject(effectsArea.text, "Effects")
        if (!effects)
            return
        if (nameField.text.trim().length === 0) {
            root.editorError = "Rule name cannot be empty."
            return
        }
        root.bridge.perform("rules.upsert", {
            kind: root.editorKind,
            id: root.editorId,
            name: nameField.text.trim(),
            match: match,
            effects: effects
        })
    }

    Connections {
        target: root.bridge
        function onActionFinished(action, ok) {
            if (ok && String(action).startsWith("rules."))
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
                title: "Rules"
                subtitle: "Window, workspace and layer behavior"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Rule configuration unavailable"
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
                description: "Rules are still inspected from the real configuration. Editing activates only when the certified Maho user overlay is loaded."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            SettingCard {
                visible: root.editorOpen
                title: root.editorId.length > 0 || root.originalWorkspaceFields
                    ? "Edit " + root.editorKind + " rule"
                    : "New " + root.editorKind + " rule"
                description: "Writes are syntax-checked, live-reloaded, observed, and rolled back on failure."
                surface: theme.surfaceElevated
                borderColor: theme.controlActiveRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoTextField {
                    id: nameField
                    visible: root.editorKind !== "workspace"
                    Layout.fillWidth: true
                    placeholderText: "Rule name"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                Text {
                    Layout.fillWidth: true
                    text: root.editorKind === "workspace" ? "Fields" : "Match"
                    color: theme.textSecondary
                    font.pixelSize: 11
                }

                MahoTextArea {
                    id: matchArea
                    Layout.fillWidth: true
                    placeholderText: root.editorKind === "workspace"
                        ? "Workspace rule fields as JSON"
                        : "Match conditions as JSON"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                Text {
                    visible: root.editorKind !== "workspace"
                    Layout.fillWidth: true
                    text: "Effects"
                    color: theme.textSecondary
                    font.pixelSize: 11
                }

                MahoTextArea {
                    id: effectsArea
                    visible: root.editorKind !== "workspace"
                    Layout.fillWidth: true
                    placeholderText: "Effects as JSON"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                Text {
                    visible: root.editorError.length > 0
                    Layout.fillWidth: true
                    text: root.editorError
                    color: theme.textSecondary
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }

                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }

                    ChoicePill {
                        text: "Cancel"
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.editorOpen = false
                    }

                    ChoicePill {
                        text: "Save"
                        selected: true
                        enabled: !root.bridge.actionBusy
                        accent: theme.accent
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.saveEditor()
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Window rules"
                description: "Rules applied to application windows."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                ChoicePill {
                    text: "Add window rule"
                    selected: true
                    visible: !!root.pageState.canAddWindowRule
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.openNew("window")
                }

                Repeater {
                    model: root.pageState.windowRules || []

                    delegate: ManagedListRow {
                        id: windowRuleRow
                        required property var modelData
                        required property int index
                        title: windowRuleRow.modelData.name || "Window rule"
                        description: root.objectSummary(windowRuleRow.modelData.match) + " → " + root.objectSummary(windowRuleRow.modelData.effects)
                        trailingText: windowRuleRow.modelData.userOwned ? "Maho" : "System"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.windowRules || []).length - 1

                        ChoicePill {
                            visible: !!windowRuleRow.modelData.canEdit
                            text: "Edit"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openEdit("window", windowRuleRow.modelData)
                        }

                        ChoicePill {
                            visible: !!windowRuleRow.modelData.canDelete
                            text: "Delete"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("rules.delete", {
                                kind: "window",
                                id: windowRuleRow.modelData.id
                            })
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Workspace rules"
                description: "Workspace placement and workspace-scoped configuration."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                ChoicePill {
                    text: "Add workspace rule"
                    selected: true
                    visible: !!root.pageState.canAddWorkspaceRule
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.openNew("workspace")
                }

                Repeater {
                    model: root.pageState.workspaceRules || []

                    delegate: ManagedListRow {
                        id: workspaceRuleRow
                        required property var modelData
                        required property int index
                        title: workspaceRuleRow.modelData.name || "Workspace rule"
                        description: root.objectSummary(workspaceRuleRow.modelData.fields)
                        trailingText: workspaceRuleRow.modelData.userOwned ? "Maho" : "System"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.workspaceRules || []).length - 1

                        ChoicePill {
                            visible: !!workspaceRuleRow.modelData.canEdit
                            text: "Edit"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openEdit("workspace", workspaceRuleRow.modelData)
                        }

                        ChoicePill {
                            visible: !!workspaceRuleRow.modelData.canDelete
                            text: "Delete"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("rules.workspaceDelete", {
                                fields: workspaceRuleRow.modelData.fields
                            })
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Layer rules"
                description: "Rules applied to shell and layer surfaces."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                ChoicePill {
                    text: "Add layer rule"
                    selected: true
                    visible: !!root.pageState.canAddLayerRule
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.openNew("layer")
                }

                Repeater {
                    model: root.pageState.layerRules || []

                    delegate: ManagedListRow {
                        id: layerRuleRow
                        required property var modelData
                        required property int index
                        title: layerRuleRow.modelData.name || "Layer rule"
                        description: root.objectSummary(layerRuleRow.modelData.match) + " → " + root.objectSummary(layerRuleRow.modelData.effects)
                        trailingText: layerRuleRow.modelData.userOwned ? "Maho" : "System"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.layerRules || []).length - 1

                        ChoicePill {
                            visible: !!layerRuleRow.modelData.canEdit
                            text: "Edit"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openEdit("layer", layerRuleRow.modelData)
                        }

                        ChoicePill {
                            visible: !!layerRuleRow.modelData.canDelete
                            text: "Delete"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("rules.delete", {
                                kind: "layer",
                                id: layerRuleRow.modelData.id
                            })
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
