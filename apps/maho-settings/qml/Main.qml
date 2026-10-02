import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import "components"

ApplicationWindow {
    id: root

    width: 1200
    height: 840
    minimumWidth: 700
    minimumHeight: 440
    visible: true
    title: "Maho Settings"
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    readonly property bool reducedTransparency: {
        const appearance = settingsBridge.state.appearance
        return appearance ? !!appearance.reducedTransparency : false
    }
    readonly property bool reducedMotion: {
        const appearance = settingsBridge.state.appearance
        return appearance ? !!appearance.reducedMotion : false
    }
    readonly property real sidebarWidth: width < 980 ? 232 : 272
    property string currentRoute: "appearance"
    property string currentTarget: "appearance"

    property var sections: [
        {
            label: "Core",
            items: [
                { route: "appearance", label: "Appearance", icon: "preferences-desktop-theme" },
                { route: "displays", label: "Displays", icon: "video-display" },
                { route: "sound", label: "Sound", icon: "audio-volume-high" },
                { route: "input", label: "Input", icon: "input-keyboard" },
                { route: "power", label: "Power", icon: "battery" },
                { route: "notifications", label: "Notifications", icon: "preferences-system-notifications" },
                { route: "applications", label: "Applications", icon: "applications-other" },
                { route: "region", label: "Region & Time", icon: "preferences-desktop-locale" }
            ]
        },
        {
            label: "Desktop",
            items: [
                { route: "shortcuts", label: "Shortcuts", icon: "preferences-desktop-keyboard-shortcuts" },
                { route: "rules", label: "Rules", icon: "preferences-system-windows" },
                { route: "motion", label: "Motion", icon: "preferences-desktop-effects" },
                { route: "session", label: "Session", icon: "system-run" }
            ]
        },
        {
            label: "System",
            items: [
                { route: "configuration", label: "Configuration", icon: "preferences-system" },
                { route: "diagnostics", label: "Diagnostics", icon: "utilities-system-monitor" },
                { route: "about", label: "About", icon: "help-about" }
            ]
        }
    ]

    MahoSettingsTheme {
        id: theme
        palette: mahoPalette
        reducedTransparency: root.reducedTransparency
        reducedMotion: root.reducedMotion
    }

    function canonicalRoute(route) {
        return route === "system" ? "about" : route
    }

    function pageSource(route) {
        switch (route) {
        case "appearance": return "pages/AppearancePage.qml"
        case "displays": return "pages/DisplaysPage.qml"
        case "sound": return "pages/SoundPage.qml"
        case "input": return "pages/InputPage.qml"
        case "power": return "pages/PowerPage.qml"
        case "notifications": return "pages/NotificationsPage.qml"
        case "applications": return "pages/ApplicationsPage.qml"
        case "region": return "pages/RegionPage.qml"
        case "shortcuts": return "pages/ShortcutsPage.qml"
        case "motion": return "pages/MotionPage.qml"
        case "configuration": return "pages/ConfigurationPage.qml"
        case "diagnostics": return "pages/DiagnosticsPage.qml"
        case "about": return "pages/AboutPage.qml"
        default: return "pages/DeferredPage.qml"
        }
    }

    function selectRoute(route, target) {
        const canonical = canonicalRoute(route)
        currentRoute = canonical
        currentTarget = target || canonical
    }


    Rectangle {
        id: shell
        anchors.fill: parent
        radius: 26
        clip: true
        color: theme.shellFill
        border.width: 1
        border.color: theme.shellRim
        antialiasing: true

        DragHandler {
            target: null
            acceptedButtons: Qt.LeftButton
            onActiveChanged: {
                if (active)
                    root.startSystemMove()
            }
        }

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 25
            color: "transparent"
            border.width: 1
            border.color: theme.shellInnerRim
            antialiasing: true
        }

        SettingsSidebar {
            id: sidebar
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: root.sidebarWidth
            sections: root.sections
            currentRoute: root.currentRoute
            theme: theme
            searchResults: settingsBridge.searchResults
            onRouteSelected: function(route) { root.selectRoute(route) }
            onSearchRequested: function(query) { settingsBridge.search(query) }
            onSearchResultSelected: function(route, target) { root.selectRoute(route, target) }
        }

        Rectangle {
            id: divider
            anchors.left: sidebar.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 1
            color: theme.divider
        }

        Rectangle {
            id: contentSurface
            anchors.left: divider.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            color: theme.contentFill

            Loader {
                id: pageLoader
                anchors.fill: parent
                anchors.leftMargin: root.width < 980 ? 28 : 38
                anchors.rightMargin: root.width < 980 ? 28 : 38
                anchors.topMargin: root.height < 700 ? 26 : 36
                anchors.bottomMargin: 28
                source: root.pageSource(root.currentRoute)

                onLoaded: {
                    if (!item)
                        return
                    item.bridge = settingsBridge
                    item.themePalette = mahoPalette
                    if (item.hasOwnProperty("targetRoute"))
                        item.targetRoute = root.currentTarget
                }
            }
        }

        Rectangle {
            id: errorToast
            visible: settingsBridge.error.length > 0 && !settingsBridge.loading
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.rightMargin: 22
            anchors.bottomMargin: 20
            width: Math.min(440, root.width - root.sidebarWidth - 54)
            height: visible ? Math.max(44, errorMessage.implicitHeight + 20) : 0
            radius: 13
            color: theme.reducedTransparency
                ? theme.surfaceElevated
                : theme.alpha(theme.surfaceElevated, 0.94)
            border.width: 1
            border.color: theme.alpha(mahoPalette.accent, 0.22)
            z: 50

            Text {
                id: errorMessage
                anchors.fill: parent
                anchors.margins: 10
                text: settingsBridge.error
                color: theme.textBody
                font.pixelSize: 12
                wrapMode: Text.WordWrap
                verticalAlignment: Text.AlignVCenter
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
