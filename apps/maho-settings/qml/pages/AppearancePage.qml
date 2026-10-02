import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../components"

Item {
    id: root

    property var bridge
    property var themePalette
    readonly property var pageState: bridge && bridge.state.appearance ? bridge.state.appearance : ({})
    readonly property bool reducedTransparency: !!root.pageState.reducedTransparency

    MahoSettingsTheme {
        id: theme
        palette: root.themePalette
        reducedTransparency: root.reducedTransparency
    }

    function wallpaperSource() {
        const wall = root.pageState.wallpaper || ({})
        return wall.previewPath ? "file://" + wall.previewPath : ""
    }

    ScrollView {
        anchors.fill: parent
        clip: true
        ScrollBar.vertical: MahoScrollBar {
            foreground: theme.textPrimary
            reducedMotion: theme.reducedMotion
        }
        contentWidth: availableWidth

        ColumnLayout {
            width: Math.max(0, root.width - 12)
            spacing: 12

            PageHeader {
                title: "Appearance"
                subtitle: "Customize the visual experience of MahoOS"
                foreground: theme.textPrimary
                muted: theme.textSecondary
            }

            Item { Layout.preferredHeight: 6 }

            StatePanel {
                visible: !root.pageState.available && !root.bridge.loading
                title: "Appearance state unavailable"
                detail: root.pageState.error || root.bridge.error
                retryVisible: true
                surface: theme.surfaceElevated
                borderColor: theme.rowRim
                foreground: theme.textPrimary
                muted: theme.textSecondary
                accent: theme.accent
                onRetryRequested: root.bridge.refresh()
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Appearance mode"
                description: "Choose how MahoOS looks"
                iconName: "preferences-desktop-theme"
                theme: theme

                MahoSegmentedControl {
                    theme: theme
                    busy: root.bridge.actionBusy
                    currentValue: root.pageState.mode || "dark"
                    options: [
                        { label: "Dark", value: "dark" },
                        { label: "Light", value: "light" }
                    ]
                    onSelected: function(value) {
                        if (!root.bridge.actionBusy && value !== root.pageState.mode)
                            root.bridge.perform("appearance.mode", { mode: value })
                    }
                }
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Wallpaper"
                description: "Choose wallpaper and derive the MahoOS color palette"
                iconName: "image-x-generic"
                theme: theme
                interactive: true
                onActivated: root.bridge.openWallpaperPicker()

                Rectangle {
                    width: 150
                    height: 62
                    radius: 10
                    clip: true
                    color: theme.controlFill
                    border.width: 1
                    border.color: theme.controlRim

                    Image {
                        anchors.fill: parent
                        source: root.wallpaperSource()
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: true
                        smooth: true
                        visible: source.toString().length > 0
                    }
                }

                Text {
                    text: "›"
                    color: theme.textSecondary
                    font.pixelSize: 24
                    font.weight: Font.Light
                    verticalAlignment: Text.AlignVCenter
                }
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Reduce motion"
                description: "Minimize animations across MahoOS"
                iconName: "preferences-desktop-effects"
                theme: theme

                MahoSwitch {
                    busy: root.bridge.actionBusy
                        reducedMotion: root.bridge && root.bridge.state.appearance ? !!root.bridge.state.appearance.reducedMotion : false
                    checked: !!root.pageState.reducedMotion
                    enabled: !!root.pageState.runtimeHooksAvailable && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) { root.bridge.perform("appearance.reducedMotion", { enabled: value }) }
                }
            }

            AppearanceRow {
                visible: !!root.pageState.available
                title: "Reduce transparency"
                description: "Reduce blur and transparency effects"
                iconName: "preferences-desktop-effects"
                theme: theme

                MahoSwitch {
                    busy: root.bridge.actionBusy
                        reducedMotion: root.bridge && root.bridge.state.appearance ? !!root.bridge.state.appearance.reducedMotion : false
                    checked: !!root.pageState.reducedTransparency
                    enabled: !!root.pageState.runtimeHooksAvailable && !root.bridge.actionBusy
                    accent: theme.accent
                    foreground: theme.textPrimary
                    muted: theme.textSecondary
                    onToggleRequested: function(value) { root.bridge.perform("appearance.reducedTransparency", { enabled: value }) }
                }
            }

            Item { Layout.preferredHeight: 8 }
        }
    }
}
