import QtQuick

Item {
    id: rail

    property var theme
    property int activeWorkspace: 1
    property bool vertical: false
    property bool switching: false

    readonly property int slotCount: 5
    readonly property int dotSize: 5
    readonly property int gap: 7
    readonly property int markerLength: 15
    readonly property int step: dotSize + gap
    readonly property int trackLength: slotCount * dotSize + (slotCount - 1) * gap
    readonly property int markerMargin: Math.floor((markerLength - dotSize) / 2)
    readonly property int activeSlot: Math.max(0, Math.min(slotCount - 1, activeWorkspace - 1))

    implicitWidth: vertical ? markerLength : trackLength + markerMargin * 2
    implicitHeight: vertical ? trackLength + markerMargin * 2 : markerLength

    Repeater {
        model: rail.slotCount

        delegate: Rectangle {
            required property int index

            width: rail.dotSize
            height: rail.dotSize
            radius: rail.dotSize / 2

            x: rail.vertical
                ? (rail.width - width) / 2
                : rail.markerMargin + index * rail.step
            y: rail.vertical
                ? rail.markerMargin + index * rail.step
                : (rail.height - height) / 2

            color: rail.theme
                ? rail.theme.alpha(rail.theme.muted, 0.30)
                : "#707078"

            Behavior on color { ColorAnimation { duration: 180 } }
        }
    }

    Rectangle {
        id: activeMarker

        width: rail.vertical ? rail.dotSize : (rail.switching ? rail.markerLength : rail.dotSize)
        height: rail.vertical ? (rail.switching ? rail.markerLength : rail.dotSize) : rail.dotSize
        radius: rail.dotSize / 2

        // The active marker is one physical object moving over five fixed
        // workspace slots. Rapid workspace changes simply retarget the same
        // animation, so 1 -> 2 -> 3 -> 4 visibly travels across the rail.
        x: rail.vertical
            ? (rail.width - width) / 2
            : rail.activeSlot * rail.step + (rail.switching ? 0 : rail.markerMargin)
        y: rail.vertical
            ? rail.activeSlot * rail.step + (rail.switching ? 0 : rail.markerMargin)
            : (rail.height - height) / 2

        color: rail.theme ? rail.theme.primary : "white"

        Behavior on width {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        Behavior on height {
            NumberAnimation { duration: 145; easing.type: Easing.OutCubic }
        }

        Behavior on x {
            enabled: !rail.vertical
            NumberAnimation {
                duration: 220
                easing.type: Easing.OutCubic
            }
        }

        Behavior on y {
            enabled: rail.vertical
            NumberAnimation {
                duration: 220
                easing.type: Easing.OutCubic
            }
        }

        Behavior on color { ColorAnimation { duration: 180 } }
    }
}
