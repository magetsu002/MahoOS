import QtQuick
import Quickshell

PanelWindow {
    id: reservation

    required property var dock
    property int breathingRoom: 8
    property int horizontalBarThickness: 40
    property int verticalBarThickness: 46

    readonly property bool vertical:
        dock.edge === "left" || dock.edge === "right"

    readonly property int reservedThickness:
        (vertical ? verticalBarThickness : horizontalBarThickness) + breathingRoom

    // The reservation is deliberately separate from the visible Maho Edge
    // surface. It reserves only the collapsed bar plus a small breathing gap;
    // expanding the control center never makes tiled windows jump around.
    anchors {
        top: dock.edge === "top" || vertical
        bottom: dock.edge === "bottom" || vertical
        left: dock.edge === "left" || !vertical
        right: dock.edge === "right" || !vertical
    }

    implicitWidth: 1
    implicitHeight: 1
    color: "transparent"
    aboveWindows: false
    focusable: false
    exclusiveZone: reservedThickness

    // This surface owns compositor layout only. It must never intercept input.
    mask: Region {}
}
