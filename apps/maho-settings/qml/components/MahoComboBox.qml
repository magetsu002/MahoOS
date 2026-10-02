pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

ComboBox {
    id: root
    property color surface: "#312e37"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property color accent: "#d0bcff"
    property bool backendOwned: false
    property int backendIndex: -1
    signal indexRequested(int index)

    function syncBackendIndex() {
        if (!root.backendOwned || root.popup.visible)
            return
        root.currentIndex = root.backendIndex
    }

    Component.onCompleted: root.syncBackendIndex()
    onBackendIndexChanged: root.syncBackendIndex()

    Connections {
        target: root
        function onActivated(index) {
            if (!root.backendOwned)
                return
            root.indexRequested(index)
            Qt.callLater(root.syncBackendIndex)
        }
    }

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 30
    hoverEnabled: true

    contentItem: Text {
        text: root.displayText
        color: root.enabled ? root.foreground : root.muted
        font.pixelSize: 12
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }

    indicator: Canvas {
        x: root.width - width - 10
        y: (root.height - height) / 2
        width: 12
        height: 8
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = root.muted
            ctx.lineWidth = 1.5
            ctx.beginPath()
            ctx.moveTo(1, 2)
            ctx.lineTo(6, 7)
            ctx.lineTo(11, 2)
            ctx.stroke()
        }
    }

    background: Rectangle {
        radius: 11
        color: root.down
            ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.085)
            : (root.hovered ? Qt.lighter(root.surface, 1.05) : root.surface)
        border.width: 1
        border.color: root.activeFocus || root.popup.visible
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.40)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
    }

    popup: Popup {
        y: root.height + 5
        width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + 10, 300)
        padding: 5
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent

        background: Rectangle {
            radius: 12
            // A popup needs stronger separation than an in-page control.
            // Preserve the derived RGB while avoiding stacked transparency
            // that can make menu labels fight with the page underneath.
            color: Qt.rgba(root.surface.r, root.surface.g, root.surface.b, 0.96)
            border.width: 1
            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.11)
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.delegateModel
            currentIndex: root.highlightedIndex
            ScrollBar.vertical: MahoScrollBar {
                foreground: root.foreground
            }
        }
    }

    delegate: ItemDelegate {
        id: delegateItem
        required property var modelData
        required property int index
        width: ListView.view.width
        height: 36
        highlighted: root.highlightedIndex === index

        contentItem: Text {
            text: root.textRole && delegateItem.modelData ? delegateItem.modelData[root.textRole] : delegateItem.modelData
            color: root.foreground
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: 8
            color: delegateItem.highlighted
                ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.13)
                : "transparent"
        }
    }
}
