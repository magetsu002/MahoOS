import QtQuick

Item {
    id: root

    property color glyphColor: Qt.rgba(1, 1, 1, 1)
    property bool disabled: false
    property real strokeScale: 0.058

    implicitWidth: 24
    implicitHeight: 24

    Canvas {
        id: canvas
        anchors.fill: parent
        renderTarget: Canvas.Image
        antialiasing: true

        onPaint: {
            const ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)

            const size = Math.min(width, height)
            const cx = width * 0.5
            const cy = height * 0.665
            const lineWidth = Math.max(1.05, size * root.strokeScale)

            ctx.strokeStyle = root.glyphColor
            ctx.fillStyle = root.glyphColor
            ctx.lineWidth = lineWidth
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            function arc(radius, start, end) {
                ctx.beginPath()
                ctx.arc(cx, cy, radius, Math.PI * start, Math.PI * end, false)
                ctx.stroke()
            }

            // A compact system-style Wi-Fi mark. Every arc shares the same
            // center axis and mirrored endpoints, so visual centering is
            // deterministic and independent of font metrics or glyph bearings.
            arc(size * 0.365, 1.195, 1.805)
            arc(size * 0.245, 1.215, 1.785)
            arc(size * 0.130, 1.255, 1.745)

            ctx.beginPath()
            ctx.arc(cx, cy, size * 0.0375, 0, Math.PI * 2, false)
            ctx.fill()

            if (root.disabled) {
                ctx.beginPath()
                ctx.lineWidth = Math.max(1.0, lineWidth * 0.88)
                ctx.moveTo(cx - size * 0.285, cy - size * 0.335)
                ctx.lineTo(cx + size * 0.285, cy + size * 0.075)
                ctx.stroke()
            }
        }

        Component.onCompleted: requestPaint()
    }

    onGlyphColorChanged: canvas.requestPaint()
    onDisabledChanged: canvas.requestPaint()
    onStrokeScaleChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()
}
