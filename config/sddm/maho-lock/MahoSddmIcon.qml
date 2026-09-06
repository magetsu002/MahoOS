import QtQuick 2.15

Canvas {
    id: root

    property string name: "lock"
    property color color: Qt.rgba(0.973, 0.984, 1.0, 0.96)
    property real lineWidth: Math.max(1.4, Math.min(width, height) * 0.085)

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    function strokeArc(ctx, cx, cy, radius, start, end) {
        ctx.beginPath()
        ctx.arc(cx, cy, radius, start, end, false)
        ctx.stroke()
    }

    onPaint: {
        const ctx = getContext("2d")
        const w = width
        const h = height
        const s = Math.min(w, h)

        ctx.clearRect(0, 0, w, h)
        ctx.save()
        ctx.strokeStyle = color
        ctx.fillStyle = color
        ctx.lineWidth = lineWidth
        ctx.lineCap = "round"
        ctx.lineJoin = "round"

        if (name === "lock") {
            ctx.beginPath()
            ctx.arc(w * 0.5, h * 0.39, s * 0.22, Math.PI, 0, false)
            ctx.stroke()
            ctx.strokeRect(w * 0.24, h * 0.40, w * 0.52, h * 0.42)
            ctx.beginPath()
            ctx.arc(w * 0.5, h * 0.59, s * 0.045, 0, Math.PI * 2)
            ctx.fill()
            ctx.fillRect(w * 0.485, h * 0.60, w * 0.03, h * 0.10)
        } else if (name === "eye") {
            ctx.beginPath()
            ctx.moveTo(w * 0.08, h * 0.5)
            ctx.bezierCurveTo(w * 0.27, h * 0.18, w * 0.73, h * 0.18, w * 0.92, h * 0.5)
            ctx.bezierCurveTo(w * 0.73, h * 0.82, w * 0.27, h * 0.82, w * 0.08, h * 0.5)
            ctx.stroke()
            strokeArc(ctx, w * 0.5, h * 0.5, s * 0.13, 0, Math.PI * 2)
        } else if (name === "power") {
            ctx.beginPath()
            ctx.arc(w * 0.5, h * 0.54, s * 0.33, -Math.PI * 0.30, Math.PI * 1.30, false)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(w * 0.5, h * 0.10)
            ctx.lineTo(w * 0.5, h * 0.52)
            ctx.stroke()
        } else if (name === "restart") {
            ctx.beginPath()
            ctx.arc(w * 0.50, h * 0.52, s * 0.32, -Math.PI * 0.12, Math.PI * 1.48, false)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(w * 0.79, h * 0.14)
            ctx.lineTo(w * 0.80, h * 0.39)
            ctx.lineTo(w * 0.57, h * 0.31)
            ctx.stroke()
        } else if (name === "keyboard") {
            ctx.strokeRect(w * 0.08, h * 0.20, w * 0.84, h * 0.60)
            for (let row = 0; row < 2; row++) {
                for (let col = 0; col < 5; col++) {
                    ctx.fillRect(w * (0.20 + col * 0.13), h * (0.34 + row * 0.16), s * 0.035, s * 0.035)
                }
            }
            ctx.fillRect(w * 0.28, h * 0.66, w * 0.44, s * 0.035)
        } else if (name === "session") {
            ctx.strokeRect(w * 0.12, h * 0.14, w * 0.76, h * 0.68)
            ctx.beginPath()
            ctx.moveTo(w * 0.30, h * 0.68)
            ctx.lineTo(w * 0.46, h * 0.51)
            ctx.lineTo(w * 0.57, h * 0.61)
            ctx.lineTo(w * 0.72, h * 0.42)
            ctx.stroke()
            ctx.beginPath()
            ctx.arc(w * 0.35, h * 0.36, s * 0.06, 0, Math.PI * 2)
            ctx.fill()
        }

        ctx.restore()
    }
}
