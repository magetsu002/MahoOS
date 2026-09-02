import QtQuick

Item {
    id: root

    property color glyphColor: Qt.rgba(1, 1, 1, 1)
    property bool disabled: false
    property real strokeScale: 0.082

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
            const cx = width / 2
            const cy = height * 0.68
            const lineWidth = Math.max(1.35, size * root.strokeScale)

            ctx.strokeStyle = root.glyphColor
            ctx.fillStyle = root.glyphColor
            ctx.lineWidth = lineWidth
            ctx.lineCap = "round"

            function wifiArc(radius) {
                ctx.beginPath()
                ctx.arc(
                    cx,
                    cy,
                    radius,
                    Math.PI * 1.17,
                    Math.PI * 1.83,
                    false
                )
                ctx.stroke()
            }

            // Geometry is symmetric around cx; unlike a font glyph, it has no
            // baseline or side-bearing bias. This keeps every Wi-Fi mark
            // optically centered at every capsule size.
            wifiArc(size * 0.36)
            wifiArc(size * 0.225)

            ctx.beginPath()
            ctx.arc(cx, cy, size * 0.060, 0, Math.PI * 2, false)
            ctx.fill()

            if (root.disabled) {
                ctx.beginPath()
                ctx.lineWidth = Math.max(1.25, lineWidth * 0.82)
                ctx.moveTo(cx - size * 0.31, cy - size * 0.37)
                ctx.lineTo(cx + size * 0.31, cy + size * 0.12)
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
