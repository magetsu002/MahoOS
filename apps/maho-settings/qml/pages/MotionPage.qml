pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root
    required property var bridge
    required property var themePalette
    readonly property var pageState: bridge && bridge.state.motion ? bridge.state.motion : ({})

    property bool editorOpen: false
    property string editorType: "animation"
    property bool animationEnabled: true

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedTransparency : false
        reducedMotion: root.bridge && root.bridge.state.appearance
            ? !!root.bridge.state.appearance.reducedMotion : false
    }

    function animationDetail(row) {
        let detail = row.enabled ? "Enabled" : "Disabled"
        detail += " · speed " + Number(row.speed || 0).toFixed(2).replace(/0+$/, "").replace(/.$/, "")
        if (row.style)
            detail += " · " + row.style
        return detail
    }

    function curvePoints(row) {
        return "(" + Number(row.x0).toFixed(2) + ", " + Number(row.y0).toFixed(2)
            + ")  (" + Number(row.x1).toFixed(2) + ", " + Number(row.y1).toFixed(2) + ")"
    }

    function openNewAnimation() {
        root.editorType = "animation"
        animationLeaf.text = ""
        animationSpeed.text = "1"
        animationCurve.text = "default"
        animationStyle.text = ""
        root.animationEnabled = true
        root.editorOpen = true
    }

    function openAnimation(row) {
        root.editorType = "animation"
        animationLeaf.text = String(row.name || "")
        animationSpeed.text = Number(row.speed || 0).toString()
        animationCurve.text = String(row.curve || "default")
        animationStyle.text = String(row.style || "")
        root.animationEnabled = !!row.enabled
        root.editorOpen = true
    }

    function openNewCurve() {
        root.editorType = "curve"
        curveName.text = ""
        curveX0.text = "0.25"
        curveY0.text = "0.10"
        curveX1.text = "0.25"
        curveY1.text = "1.00"
        root.editorOpen = true
    }

    function openCurve(row) {
        root.editorType = "curve"
        curveName.text = String(row.name || "")
        curveX0.text = Number(row.x0 || 0).toString()
        curveY0.text = Number(row.y0 || 0).toString()
        curveX1.text = Number(row.x1 || 0).toString()
        curveY1.text = Number(row.y1 || 0).toString()
        root.editorOpen = true
    }

    function saveEditor() {
        if (root.editorType === "animation") {
            root.bridge.perform("motion.animationUpsert", {
                leaf: animationLeaf.text.trim(),
                enabled: root.animationEnabled,
                speed: Number(animationSpeed.text),
                curve: animationCurve.text.trim(),
                style: animationStyle.text.trim()
            })
        } else {
            root.bridge.perform("motion.curveUpsert", {
                name: curveName.text.trim(),
                x0: Number(curveX0.text),
                y0: Number(curveY0.text),
                x1: Number(curveX1.text),
                y1: Number(curveY1.text)
            })
        }
    }

    Connections {
        target: root.bridge
        function onActionFinished(action, ok) {
            if (ok && String(action).startsWith("motion."))
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
                title: "Motion"
                subtitle: "Animations and Bézier curves"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Motion state unavailable"
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
                description: "Motion remains live-inspected. Overrides activate when the Maho user-overlay writer is loaded."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            SettingCard {
                visible: root.editorOpen
                title: root.editorType === "animation" ? "Animation override" : "Bézier curve"
                description: "The override is verified against live Hyprland state and rolled back if it does not converge."
                surface: theme.surfaceElevated
                borderColor: theme.controlActiveRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                ColumnLayout {
                    visible: root.editorType === "animation"
                    Layout.fillWidth: true
                    spacing: 8

                    MahoTextField {
                        id: animationLeaf
                        Layout.fillWidth: true
                        placeholderText: "Animation leaf, e.g. windows"
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        accent: theme.accent
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        MahoTextField {
                            id: animationSpeed
                            Layout.preferredWidth: 120
                            placeholderText: "Speed"
                            validator: DoubleValidator { bottom: 0; top: 50; decimals: 3 }
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }

                        MahoTextField {
                            id: animationCurve
                            Layout.fillWidth: true
                            placeholderText: "Curve"
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }

                        MahoTextField {
                            id: animationStyle
                            Layout.fillWidth: true
                            placeholderText: "Style (optional)"
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                    }

                    MahoSegmentedControl {
                        Layout.preferredWidth: 220
                        theme: theme
                        options: [
                            { label: "Enabled", value: "enabled" },
                            { label: "Disabled", value: "disabled" }
                        ]
                        currentValue: root.animationEnabled ? "enabled" : "disabled"
                        onSelected: function(value) {
                            root.animationEnabled = value === "enabled"
                        }
                    }
                }

                ColumnLayout {
                    visible: root.editorType === "curve"
                    Layout.fillWidth: true
                    spacing: 8

                    MahoTextField {
                        id: curveName
                        Layout.fillWidth: true
                        placeholderText: "Curve name"
                        surface: theme.controlFill
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        accent: theme.accent
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8

                        MahoTextField {
                            id: curveX0
                            Layout.fillWidth: true
                            placeholderText: "X0"
                            validator: DoubleValidator { decimals: 4 }
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                        MahoTextField {
                            id: curveY0
                            Layout.fillWidth: true
                            placeholderText: "Y0"
                            validator: DoubleValidator { decimals: 4 }
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                        MahoTextField {
                            id: curveX1
                            Layout.fillWidth: true
                            placeholderText: "X1"
                            validator: DoubleValidator { decimals: 4 }
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                        MahoTextField {
                            id: curveY1
                            Layout.fillWidth: true
                            placeholderText: "Y1"
                            validator: DoubleValidator { decimals: 4 }
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            accent: theme.accent
                        }
                    }
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
                title: "Animations"
                description: "Live overridden animation leaves. System entries can be safely shadowed by Maho."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                ChoicePill {
                    text: "Add override"
                    selected: true
                    visible: !!root.pageState.mutationAvailable
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.openNewAnimation()
                }

                Repeater {
                    model: root.pageState.animations || []

                    delegate: ManagedListRow {
                        id: animationRow
                        required property var modelData
                        required property int index
                        title: animationRow.modelData.name
                        description: root.animationDetail(animationRow.modelData)
                        trailingText: (animationRow.modelData.curve || "default")
                            + (animationRow.modelData.userOwned ? " · Maho" : " · System")
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.animations || []).length - 1

                        ChoicePill {
                            visible: !!animationRow.modelData.canOverride
                            text: animationRow.modelData.userOwned ? "Edit" : "Override"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openAnimation(animationRow.modelData)
                        }

                        ChoicePill {
                            visible: !!animationRow.modelData.canDelete
                            text: "Reset"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("motion.animationReset", {
                                leaf: animationRow.modelData.name
                            })
                        }
                    }
                }
            }

            SettingCard {
                visible: !!root.pageState.available
                title: "Bézier curves"
                description: "Live curve definitions and Maho-owned curve overrides."
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary

                ChoicePill {
                    text: "Add curve"
                    selected: true
                    visible: !!root.pageState.mutationAvailable
                    enabled: !root.bridge.actionBusy
                    accent: theme.accent
                    surface: theme.controlFill
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onClicked: root.openNewCurve()
                }

                Repeater {
                    model: root.pageState.curves || []

                    delegate: ManagedListRow {
                        id: curveRow
                        required property var modelData
                        required property int index
                        title: curveRow.modelData.name
                        description: root.curvePoints(curveRow.modelData)
                        trailingText: curveRow.modelData.userOwned ? "Maho" : "System"
                        foreground: theme.textPrimary
                        muted: theme.textSecondary
                        dividerVisible: index < (root.pageState.curves || []).length - 1

                        ChoicePill {
                            visible: !!curveRow.modelData.canOverride
                            text: curveRow.modelData.userOwned ? "Edit" : "Override"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.openCurve(curveRow.modelData)
                        }

                        ChoicePill {
                            visible: !!curveRow.modelData.canDelete
                            text: "Reset"
                            enabled: !root.bridge.actionBusy
                            accent: theme.accent
                            surface: theme.controlFill
                            foreground: theme.textPrimary
                            muted: theme.textSecondary
                            onClicked: root.bridge.perform("motion.curveReset", {
                                name: curveRow.modelData.name
                            })
                        }
                    }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
