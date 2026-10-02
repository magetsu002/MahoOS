import QtQuick
import QtQuick.Controls

ComboBox {
    id: root
    property color surface: "#312e37"
    property color foreground: "#f3eef8"
    property color muted: "#aaa3af"
    property color accent: "#d0bcff"

    implicitHeight: 38
    leftPadding: 12
    rightPadding: 30

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
        color: root.surface
        border.width: 1
        border.color: root.activeFocus
            ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.48)
            : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.09)
    }

    popup: Popup {
        y: root.height + 5
        width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + 10, 300)
        padding: 5

        background: Rectangle {
            radius: 12
            color: root.surface
            border.width: 1
            border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
        }

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: root.delegateModel
            currentIndex: root.highlightedIndex
            ScrollIndicator.vertical: ScrollIndicator {}
        }
    }

    delegate: ItemDelegate {
        required property var model
        required property int index
        width: ListView.view.width
        height: 36
        highlighted: root.highlightedIndex === index

        contentItem: Text {
            text: root.textRole ? model[root.textRole] : modelData
            color: root.foreground
            font.pixelSize: 12
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
        }

        background: Rectangle {
            radius: 8
            color: parent.highlighted
                ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.13)
                : "transparent"
        }
    }
}
