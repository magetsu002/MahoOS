pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "components"

ApplicationWindow {
    id: root

    width: 1200
    height: 840
    minimumWidth: 700
    minimumHeight: 440

    // These two objects are intentionally supplied by the native C++ context.
    // Qualify all use through root afterwards so qmllint can reason about the
    // rest of this file without treating every access as implicit scope.
    // qmllint disable unqualified
    readonly property var bridge: settingsBridge
    readonly property var paletteObject: mahoPalette
    // qmllint enable unqualified

    // Do not map a half-initialized shell. The streamed warmup normally
    // publishes Appearance in ~one frame budget, then the complete window is
    // mapped once with real palette/state and compositor placement.
    visible: !!root.bridge.state.appearance
    title: "Maho Settings"
    color: "transparent"
    flags: Qt.Window | Qt.FramelessWindowHint

    readonly property bool reducedTransparency: {
        const appearance = root.bridge.state.appearance
        return appearance ? !!appearance.reducedTransparency : false
    }
    readonly property bool reducedMotion: {
        const appearance = root.bridge.state.appearance
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
        palette: root.paletteObject
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
        case "rules": return "pages/RulesPage.qml"
        case "motion": return "pages/MotionPage.qml"
        case "session": return "pages/SessionPage.qml"
        case "configuration": return "pages/ConfigurationPage.qml"
        case "diagnostics": return "pages/DiagnosticsPage.qml"
        case "about": return "pages/AboutPage.qml"
        default: return "pages/DeferredPage.qml"
        }
    }

    function pageProperties(route, target) {
        const properties = {
            bridge: root.bridge,
            themePalette: root.paletteObject
        }
        if (route === "about")
            properties.targetRoute = target || route
        return properties
    }

    function loadPage(route, target) {
        pageLoader.setSource(
            root.pageSource(route),
            root.pageProperties(route, target)
        )
    }

    function selectRoute(route, target) {
        const canonical = canonicalRoute(route)
        const nextTarget = target || canonical
        const sameComponent = root.pageSource(canonical) === root.pageSource(root.currentRoute)

        currentTarget = nextTarget

        // Rules and Session intentionally share one deferred component, and
        // search can target a subsection of About. Do not destroy/recreate the
        // page when only that in-page target changed.
        if (sameComponent && pageLoader.item) {
            currentRoute = canonical
            if (pageLoader.item.hasOwnProperty("targetRoute"))
                pageLoader.item.targetRoute = nextTarget
            return
        }

        // Initial properties are applied before the new QML item is exposed.
        // This avoids one-frame empty/default page state during navigation.
        root.loadPage(canonical, nextTarget)
        currentRoute = canonical
    }

    Component.onCompleted: root.loadPage(root.currentRoute, root.currentTarget)

    Rectangle {
        id: shell
        anchors.fill: parent
        radius: 26
        clip: true
        color: theme.shellFill
        border.width: 1
        border.color: theme.shellRim
        antialiasing: true

        // Keep window dragging out of the interactive surface. A shell-wide
        // DragHandler made clicks and small pointer motions feel sticky because
        // controls and navigation competed with a window move gesture.
        Item {
            id: dragRegion
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 26
            z: 40

            DragHandler {
                target: null
                acceptedButtons: Qt.LeftButton
                onActiveChanged: {
                    if (active)
                        root.startSystemMove()
                }
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
            searchResults: root.bridge.searchResults
            onRouteSelected: function(route) { root.selectRoute(route) }
            onSearchRequested: function(query) { root.bridge.search(query) }
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
                asynchronous: false
            }
        }

        Rectangle {
            id: errorToast
            visible: root.bridge.error.length > 0 && !root.bridge.loading
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
            border.color: theme.alpha(root.paletteObject.accent, 0.22)
            z: 50

            Text {
                id: errorMessage
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: root.bridge.error
                color: theme.textBody
                font.pixelSize: 12
                wrapMode: Text.WordWrap
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
