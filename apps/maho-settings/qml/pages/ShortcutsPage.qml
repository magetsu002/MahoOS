pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.shortcuts ? bridge.state.shortcuts : ({})

    property bool editorOpen: false
    property string originalChord: ""
    property string originalSubmap: ""
    property bool replaceExisting: false

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function filteredBinds() {
        const rows = root.pageState.binds || []
        const q = filterField.text.trim().toLowerCase()
        if (q.length === 0)
            return rows
        return rows.filter(function(row) {
            return String(row.chord || "").toLowerCase().includes(q)
                || String(row.description || "").toLowerCase().includes(q)
                || String(row.command || "").toLowerCase().includes(q)
                || String(row.submap || "").toLowerCase().includes(q)
        })
    }

    function openNew() {
        root.originalChord = ""
        root.originalSubmap = ""
        root.replaceExisting = false
        chordField.text = ""
        commandField.text = ""
        descriptionField.text = ""
        submapField.text = ""
        root.editorOpen = true
    }

    function openEdit(row) {
        root.originalChord = String(row.chord || "")
        root.originalSubmap = String(row.submap || "")
        root.replaceExisting = !row.userOwned
        chordField.text = root.originalChord
        commandField.text = String(row.command || "")
        descriptionField.text = String(row.description || "")
        submapField.text = root.originalSubmap
        root.editorOpen = true
    }

    function saveEditor() {
        root.bridge.perform("shortcuts.upsert", {
            chord: chordField.text.trim(),
            command: commandField.text.trim(),
            description: descriptionField.text.trim(),
            submap: submapField.text.trim(),
            originalChord: root.originalChord,
            originalSubmap: root.originalSubmap,
            replaceExisting: root.replaceExisting
        })
    }

    Connections {
        target: root.bridge
        function onActionFinished(action, ok) {
            if (ok && String(action).startsWith("shortcuts."))
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
                title: "Shortcuts"
                subtitle: "Keyboard shortcuts, overrides and submaps"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Shortcut state unavailable"
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
                description: "Shortcuts are still read from the real Hyprland configuration. Editing becomes available when the Maho user-overlay loader is deployed."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            SettingCard {
                visible: root.editorOpen
                title: root.originalChord.length > 0 ? "Edit shortcut" : "New shortcut"
                description: "Maho writes only to its user overlay and verifies the live bind after reload."
                surface: theme.surfaceElevated
                borderColor: theme.controlActiveRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                MahoTextField {
                    id: chordField
                    Layout.fillWidth: true
                    placeholderText: "Chord, e.g. SUPER + CTRL + T"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                MahoTextField {
                    id: commandField
                    Layout.fillWidth: true
                    placeholderText: "Command"
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    MahoTextField {
                        id: descriptionField
                        Layout.fillWidth: true
                        placeholderText: "Description"
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        accent: theme.accent
                    }

                    MahoTextField {
                        id: submapField
                        Layout.preferredWidth: 190
                        placeholderText: "Submap (optional)"
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        accent: theme.accent
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8

                    Text {
                        text: "Override existing assignment"
                        color: theme.textSecondary
                        font.pixelSize: 11
                    }

                    MahoSwitch {
                        checked: root.replaceExisting
                        enabled: !root.bridge.actionBusy
                        busy: false
                        reducedMotion: theme.reducedMotion
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onToggleRequested: function(value) {
                            root.replaceExisting = value
                        }
                    }

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
                        label: "Save shortcut"
                        emphasized: true
                        enabled: !root.bridge.actionBusy
                            && chordField.text.trim().length > 0
                            && commandField.text.trim().length > 0
                        accent: theme.accent
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        onClicked: root.saveEditor()
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Active shortcuts"
                description: String(root.pageState.count || 0) + " shortcuts observed from the current Hyprland configuration."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                headerActionIcon: root.pageState.mutationAvailable ? "add" : ""
                headerActionLabel: "Add shortcut"
                headerActionEnabled: !root.bridge.actionBusy
                onHeaderActionTriggered: root.openNew()

                MahoTextField {
                    id: filterField
                    Layout.fillWidth: true
                    placeholderText: "Filter shortcuts..."
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    accent: theme.accent
                }

                Repeater {
                    model: root.filteredBinds()

                    delegate: ManagedListRow {
                        id: shortcutRow
                        required property var modelData
                        required property int index
                        title: shortcutRow.modelData.chord || "Unknown shortcut"
                        description: shortcutRow.modelData.description || shortcutRow.modelData.command || shortcutRow.modelData.action || "Shortcut action"
                        trailingText: shortcutRow.modelData.submap
                            ? "Submap · " + shortcutRow.modelData.submap
                            : (shortcutRow.modelData.userOwned ? "Maho override" : "System")
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < root.filteredBinds().length - 1

                        MahoIconButton {
                            visible: !!shortcutRow.modelData.canOverride
                            iconName: "edit"
                            label: shortcutRow.modelData.userOwned ? "Edit shortcut" : "Override shortcut"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openEdit(shortcutRow.modelData)
                        }

                        MahoIconButton {
                            visible: !!shortcutRow.modelData.canOverride && !shortcutRow.modelData.userOwned
                            iconName: "disable"
                            label: "Disable shortcut"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("shortcuts.disable", {
                                chord: shortcutRow.modelData.chord,
                                submap: shortcutRow.modelData.submap || ""
                            })
                        }

                        MahoIconButton {
                            visible: !!shortcutRow.modelData.userOwned
                            iconName: "reset"
                            label: "Restore inherited shortcut"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("shortcuts.reset", {
                                chord: shortcutRow.modelData.chord,
                                submap: shortcutRow.modelData.submap || ""
                            })
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
