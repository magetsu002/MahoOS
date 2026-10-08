pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root

    property var sections: []
    property string currentRoute: "appearance"
    property var theme
    property var searchResults: []
    property bool searchPending: false
    signal routeSelected(string route)
    signal searchRequested(string query)
    signal searchResultSelected(string route, string target)

    color: root.theme.sidebarFill

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 16
        anchors.rightMargin: 16
        anchors.topMargin: 30
        anchors.bottomMargin: 20
        spacing: 0

        ColumnLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 10
            spacing: 1

            Text {
                text: "MahoOS"
                color: root.theme.textPrimary
                font.pixelSize: 20
                font.weight: Font.Medium
                font.letterSpacing: -0.25
            }

            Text {
                text: "Settings"
                color: root.theme.textSecondary
                font.pixelSize: 13
            }
        }

        Item { Layout.preferredHeight: 18 }

        TextField {
            id: searchField
            Layout.fillWidth: true
            implicitHeight: 41
            leftPadding: 39
            rightPadding: 12
            topPadding: 0
            bottomPadding: 0
            placeholderText: "Search settings..."
            placeholderTextColor: root.theme.textFaint
            color: root.theme.textPrimary
            font.pixelSize: 13
            selectByMouse: true
            background: Rectangle {
                radius: 12
                color: searchField.hovered
                    ? root.theme.mix(root.theme.searchFill, root.theme.foreground, 0.025)
                    : root.theme.searchFill
                border.width: 1
                border.color: searchField.activeFocus
                    ? root.theme.searchFocusRim
                    : root.theme.rowRim
            }

            MahoIcon {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                width: 17
                height: 17
                name: "system-search"
                tone: root.theme.textSecondary
                opacity: 0.78
            }

            onTextChanged: {
                searchPopup.close()
                searchDelay.restart()
            }
            onActiveFocusChanged: {
                if (!activeFocus)
                    searchPopup.close()
                else if (!root.searchPending && text.trim().length > 0 && root.searchResults.length > 0)
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
                width: Math.max(searchField.width, 300)
                padding: 6
                modal: false
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

                background: Rectangle {
                    radius: 14
                    color: root.theme.reducedTransparency
                        ? root.theme.surfaceElevated
                        : root.theme.alpha(root.theme.surfaceElevated, 0.94)
                    border.width: 1
                    border.color: root.theme.shellRim
                }

                contentItem: ListView {
                    id: resultList
                    clip: true
                    implicitHeight: Math.min(contentHeight, 340)
                    model: root.searchResults
                    spacing: 2

                    delegate: Rectangle {
                        id: resultRow
                        required property var modelData
                        width: resultList.width
                        height: 52
                        radius: 10
                        color: resultHover.hovered ? root.theme.navHover : "transparent"

                        Column {
                            anchors.left: parent.left
                            anchors.leftMargin: 11
                            anchors.right: parent.right
                            anchors.rightMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 2

                            Text {
                                width: parent.width
                                text: resultRow.modelData.title || resultRow.modelData.label
                                color: root.theme.textPrimary
                                font.pixelSize: 13
                                font.weight: Font.Medium
                                elide: Text.ElideRight
                            }

                            Text {
                                width: parent.width
                                text: resultRow.modelData.category || "Settings"
                                color: root.theme.textSecondary
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }

                        HoverHandler { id: resultHover }
                        TapHandler {
                            onTapped: {
                                const route = resultRow.modelData.route
                                const target = resultRow.modelData.target || route
                                searchPopup.close()
                                searchField.text = ""
                                root.searchResultSelected(route, target)
                            }
                        }
                    }
                }
            }
        }

        Timer {
            id: searchDelay
            interval: 90
            repeat: false
            onTriggered: {
                const query = searchField.text.trim()
                root.searchPending = query.length > 0
                root.searchRequested(query)
                if (query.length === 0)
                    searchPopup.close()
            }
        }

        Connections {
            target: root
            function onSearchResultsChanged() {
                if (!root.searchPending)
                    return
                root.searchPending = false
                if (searchField.activeFocus
                        && searchField.text.trim().length > 0
                        && root.searchResults.length > 0) {
                    searchPopup.open()
                } else {
                    searchPopup.close()
                }
            }
        }

        Item { Layout.preferredHeight: 12 }

        Flickable {
            id: navFlick
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentWidth: width
            contentHeight: navColumn.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            flickDeceleration: 3000

            Column {
                id: navColumn
                width: navFlick.width
                spacing: 0

                Repeater {
                    model: root.sections

                    delegate: Column {
                        id: sectionGroup
                        required property var modelData
                        required property int index
                        width: navColumn.width
                        spacing: 1

                        MahoSectionLabel {
                            width: parent.width
                            height: 15
                            text: sectionGroup.modelData.label
                            textColor: root.theme.textSecondary
                        }

                        Repeater {
                            model: sectionGroup.modelData.items

                            delegate: MahoSidebarItem {
                                required property var modelData
                                width: parent.width
                                theme: root.theme
                                label: modelData.label
                                route: modelData.route
                                iconName: modelData.icon
                                selected: root.currentRoute === modelData.route
                                onActivated: function(route) { root.routeSelected(route) }
                            }
                        }

                        Item { width: 1; height: 5 }

                        Rectangle {
                            width: parent.width - 18
                            height: 1
                            x: 9
                            color: root.theme.divider
                            visible: sectionGroup.index < root.sections.length - 1
                        }

                        Item {
                            width: 1
                            height: visible ? 6 : 0
                            visible: sectionGroup.index < root.sections.length - 1
                        }
                    }
                }
            }
        }
    }
}
