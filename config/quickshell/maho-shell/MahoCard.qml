import QtQuick

Rectangle {
    id: card

    property var theme
    property bool interactive: false
    property bool emphasized: false
    property bool hovered: hover.hovered

    signal activated()

    radius: 13

    color: theme
        ? theme.alpha(
            emphasized ? theme.primary : theme.foreground,
            hovered && interactive
                ? (emphasized ? 0.15 : 0.075)
                : (emphasized ? 0.085 : 0.035)
          )
        : "#252229"

    border.width: 1
    border.color: theme
        ? theme.alpha(
            emphasized ? theme.primary : theme.outline,
            hovered && interactive ? 0.24 : 0.12
          )
        : "#404047"

    Behavior on color {
        ColorAnimation { duration: 150 }
    }

    Behavior on border.color {
        ColorAnimation { duration: 150 }
    }

    HoverHandler {
        id: hover
        enabled: card.interactive
    }

    TapHandler {
        enabled: card.interactive
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: card.activated()
    }
}
