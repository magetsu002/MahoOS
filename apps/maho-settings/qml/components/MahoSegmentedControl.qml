pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property var theme
    property var options: []
    property string currentValue: ""
    property bool busy: false
    property bool optimisticActive: false
    property string optimisticValue: ""
    readonly property string visualValue: optimisticActive ? optimisticValue : currentValue
    signal selected(string value)

    implicitWidth: Math.max(220, options.length * 96)
    implicitHeight: 40
    radius: 12
    color: root.theme.controlFill
    border.width: 1
    border.color: root.theme.controlRim
    antialiasing: true

    function request(value) {
        if (root.busy || value === root.currentValue)
            return
        root.optimisticValue = value
        root.optimisticActive = true
        optimisticFallback.restart()
        root.selected(value)
    }

    onCurrentValueChanged: {
        if (root.optimisticActive && root.currentValue === root.optimisticValue) {
            root.optimisticActive = false
            optimisticFallback.stop()
        }
    }

    onBusyChanged: {
        if (!root.busy && root.optimisticActive)
            Qt.callLater(function() { root.optimisticActive = false })
    }

    Timer {
        id: optimisticFallback
        interval: 3000
        repeat: false
        onTriggered: root.optimisticActive = false
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 1
        spacing: 0

        Repeater {
            model: root.options

            delegate: Rectangle {
                id: segment
                required property var modelData
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 11
                color: tap.pressed
                    ? root.theme.controlPressed
                    : root.visualValue === segment.modelData.value
                        ? root.theme.controlActive
                        : (hover.hovered ? root.theme.controlHover : "transparent")

                Text {
                    anchors.centerIn: parent
                    text: segment.modelData.label
                    color: root.visualValue === segment.modelData.value
                        ? root.theme.textPrimary
                        : root.theme.textSecondary
                    font.pixelSize: 12
                    font.weight: root.visualValue === segment.modelData.value ? Font.Medium : Font.Normal
                }

                HoverHandler { id: hover }
                TapHandler {
                    id: tap
                    onTapped: root.request(segment.modelData.value)
                }

                Behavior on color {
                    ColorAnimation { duration: root.theme.reducedMotion ? 0 : 110 }
                }
            }
        }
    }
}
