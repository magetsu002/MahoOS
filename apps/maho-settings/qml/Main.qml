import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "components"

ApplicationWindow {
    id: root

    width: 1120
    height: 760
    minimumWidth: 700
    minimumHeight: 500
    visible: true
    title: "Maho Settings"
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    readonly property color baseBackground: mahoPalette.background
    readonly property color surface: mahoPalette.surface
    readonly property color surfaceElevated: mahoPalette.surfaceElevated
    readonly property color foreground: mahoPalette.foreground
    readonly property color muted: mahoPalette.muted
    readonly property color accent: mahoPalette.accent
    readonly property color borderColor: mahoPalette.border
    readonly property bool reducedTransparency: {
        const appearance = settingsBridge.state.appearance
        return appearance ? !!appearance.reducedTransparency : false
    }
    readonly property bool narrow: width < 820
    property string currentRoute: "appearance"
    property string currentTarget: "appearance"

    property var categories: [
        { route: "appearance", label: "Appearance", glyph: "A" },
        { route: "displays", label: "Displays", glyph: "D" },
        { route: "sound", label: "Sound", glyph: "S" },
        { route: "input", label: "Keyboard & Pointer", glyph: "K" },
        { route: "power", label: "Power", glyph: "P" },
        { route: "system", label: "System", glyph: "i" }
    ]

    function alpha(color, amount) {
        return Qt.rgba(color.r, color.g, color.b, amount)
    }

    function pageSource(route) {
        switch (route) {
        case "appearance": return "pages/AppearancePage.qml"
        case "displays": return "pages/DisplaysPage.qml"
        case "sound": return "pages/SoundPage.qml"
        case "input": return "pages/InputPage.qml"
        case "power": return "pages/PowerPage.qml"
        case "system": return "pages/AboutPage.qml"
        default: return "pages/DeferredPage.qml"
        }
    }

    function selectRoute(route, target) {
        currentRoute = route
        currentTarget = target || route
        searchField.text = ""
        searchPopup.close()
    }

    Rectangle {
        anchors.fill: parent
        radius: 24
        color: root.reducedTransparency
            ? root.baseBackground
            : root.alpha(root.baseBackground, 0.965)
        border.width: 1
        border.color: root.alpha(root.foreground, 0.10)

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 14
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                DragHandler {
                    target: null
                    acceptedButtons: Qt.LeftButton
                    onActiveChanged: {
                        if (active)
                            root.startSystemMove()
                    }
                }

                Text {
                    text: "Settings"
                    color: root.foreground
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }

                Item { Layout.fillWidth: true }

                TextField {
                    id: searchField
                    Layout.preferredWidth: root.narrow ? Math.min(330, root.width * 0.47) : 360
                    placeholderText: "Search settings"
                    color: root.foreground
                    placeholderTextColor: root.alpha(root.muted, 0.72)
                    selectByMouse: true
                    leftPadding: 14
                    rightPadding: 14

                    background: Rectangle {
                        radius: 13
                        color: root.alpha(root.surfaceElevated, root.reducedTransparency ? 1.0 : 0.78)
                        border.width: 1
                        border.color: searchField.activeFocus
                            ? root.alpha(root.accent, 0.50)
                            : root.alpha(root.foreground, 0.08)
                    }

                    onTextChanged: searchDebounce.restart()
                    onActiveFocusChanged: {
                        if (activeFocus && text.trim().length > 0)
                            searchPopup.open()
                    }
                    Keys.onEscapePressed: {
                        text = ""
                        searchPopup.close()
                    }

                    Popup {
                        id: searchPopup
                        x: 0
                        y: searchField.height + 8
                        width: searchField.width
                        padding: 6
                        modal: false
                        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

                        background: Rectangle {
                            radius: 16
                            color: root.surfaceElevated
                            border.width: 1
                            border.color: root.alpha(root.foreground, 0.10)
                        }

                        contentItem: ListView {
                            implicitHeight: Math.min(contentHeight, 360)
                            model: settingsBridge.searchResults
                            clip: true

                            delegate: Rectangle {
                                required property var modelData
                                width: ListView.view.width
                                height: 52
                                radius: 11
                                color: resultHover.hovered
                                    ? root.alpha(root.foreground, 0.065)
                                    : "transparent"

                                Column {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    spacing: 2

                                    Text {
                                        text: modelData.label
                                        color: root.foreground
                                        font.pixelSize: 12
                                        font.weight: Font.Medium
                                    }
                                    Text {
                                        text: modelData.deferred ? "Designed for a later V1 page" : "Open setting"
                                        color: root.muted
                                        font.pixelSize: 10
                                    }
                                }

                                HoverHandler { id: resultHover }
                                TapHandler {
                                    onTapped: root.selectRoute(modelData.route, modelData.target)
                                }
                            }
                        }
                    }
                }

                Timer {
                    id: searchDebounce
                    interval: 90
                    onTriggered: {
                        settingsBridge.search(searchField.text.trim())
                        if (searchField.text.trim().length > 0)
                            searchPopup.open()
                        else
                            searchPopup.close()
                    }
                }
            }

            ComboBox {
                id: narrowRoute
                visible: root.narrow
                Layout.fillWidth: true
                model: root.categories.map(function(item) { return item.label })
                currentIndex: root.categories.findIndex(function(item) { return item.route === root.currentRoute })
                onActivated: root.selectRoute(root.categories[currentIndex].route)
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 12

                SettingsSidebar {
                    visible: !root.narrow
                    Layout.preferredWidth: 228
                    Layout.fillHeight: true
                    model: root.categories
                    currentRoute: root.currentRoute
                    surface: root.alpha(root.surface, root.reducedTransparency ? 1.0 : 0.82)
                    foreground: root.foreground
                    muted: root.muted
                    accent: root.accent
                    borderColor: root.alpha(root.foreground, 0.08)
                    onRouteSelected: function(route) { root.selectRoute(route) }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 20
                    color: root.alpha(root.surface, root.reducedTransparency ? 1.0 : 0.62)
                    border.width: 1
                    border.color: root.alpha(root.foreground, 0.07)
                    clip: true

                    Loader {
                        id: pageLoader
                        anchors.fill: parent
                        anchors.margins: 20
                        source: root.pageSource(root.currentRoute)

                        onLoaded: {
                            if (!item)
                                return
                            item.bridge = settingsBridge
                            item.palette = mahoPalette
                            if (item.hasOwnProperty("targetRoute"))
                                item.targetRoute = root.currentTarget
                        }
                    }
                }
            }
        }
    }

    component ResizeHandle: MouseArea {
        required property int edges
        acceptedButtons: Qt.LeftButton
        cursorShape: (edges === Qt.LeftEdge || edges === Qt.RightEdge) ? Qt.SizeHorCursor
            : (edges === Qt.TopEdge || edges === Qt.BottomEdge) ? Qt.SizeVerCursor
            : Qt.SizeFDiagCursor
        onPressed: root.startSystemResize(edges)
    }

    ResizeHandle { edges: Qt.LeftEdge; anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 5 }
    ResizeHandle { edges: Qt.RightEdge; anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom; width: 5 }
    ResizeHandle { edges: Qt.TopEdge; anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; height: 5 }
    ResizeHandle { edges: Qt.BottomEdge; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 5 }
    ResizeHandle { edges: Qt.LeftEdge | Qt.TopEdge; anchors.left: parent.left; anchors.top: parent.top; width: 10; height: 10 }
    ResizeHandle { edges: Qt.RightEdge | Qt.TopEdge; anchors.right: parent.right; anchors.top: parent.top; width: 10; height: 10 }
    ResizeHandle { edges: Qt.LeftEdge | Qt.BottomEdge; anchors.left: parent.left; anchors.bottom: parent.bottom; width: 10; height: 10 }
    ResizeHandle { edges: Qt.RightEdge | Qt.BottomEdge; anchors.right: parent.right; anchors.bottom: parent.bottom; width: 10; height: 10 }
}
