import QtQuick

Canvas {
    id: root

    property string icon: "lock"
    property color strokeColor: Qt.rgba(1, 1, 1, 0.82)
    property real value: 1.0
    property real lineWidth: 1.75

    antialiasing: true

    onIconChanged: requestPaint()
    onStrokeColorChanged: requestPaint()
    onValueChanged: requestPaint()
    onLineWidthChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value))
    }

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        ctx.save()

        const scale = Math.min(width, height) / 24
        const offsetX = (width - 24 * scale) / 2
        const offsetY = (height - 24 * scale) / 2
        ctx.translate(offsetX, offsetY)
        ctx.scale(scale, scale)

        ctx.strokeStyle = root.strokeColor
        ctx.fillStyle = root.strokeColor
        ctx.lineWidth = root.lineWidth
        ctx.lineCap = "round"
        ctx.lineJoin = "round"

        if (root.icon === "lock") {
            ctx.beginPath()
            ctx.arc(12, 9.5, 4.6, Math.PI, 0)
            ctx.stroke()

            ctx.beginPath()
            ctx.moveTo(7, 10)
            ctx.lineTo(7, 19)
            ctx.quadraticCurveTo(7, 21, 9, 21)
            ctx.lineTo(15, 21)
            ctx.quadraticCurveTo(17, 21, 17, 19)
            ctx.lineTo(17, 10)
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(12, 15.3, 1.15, 0, Math.PI * 2)
            ctx.fill()
        } else if (root.icon === "eye") {
            ctx.beginPath()
            ctx.moveTo(3, 12)
            ctx.quadraticCurveTo(7.2, 6.8, 12, 6.8)
            ctx.quadraticCurveTo(16.8, 6.8, 21, 12)
            ctx.quadraticCurveTo(16.8, 17.2, 12, 17.2)
            ctx.quadraticCurveTo(7.2, 17.2, 3, 12)
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(12, 12, 2.65, 0, Math.PI * 2)
            ctx.stroke()
        } else if (root.icon === "power") {
            ctx.beginPath()
            ctx.arc(12, 13, 7.25, -Math.PI * 0.72, Math.PI * 0.72)
            ctx.stroke()

            ctx.beginPath()
            ctx.moveTo(12, 3.2)
            ctx.lineTo(12, 12)
            ctx.stroke()
        } else if (root.icon === "users") {
            ctx.beginPath()
            ctx.arc(9.2, 8.3, 3.0, 0, Math.PI * 2)
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(16.8, 9.3, 2.25, 0, Math.PI * 2)
            ctx.stroke()

            ctx.beginPath()
            ctx.moveTo(3.8, 20)
            ctx.quadraticCurveTo(4.5, 14.2, 9.2, 14.2)
            ctx.quadraticCurveTo(13.9, 14.2, 14.6, 20)
            ctx.stroke()

            ctx.beginPath()
            ctx.moveTo(14.1, 15.4)
            ctx.quadraticCurveTo(18.9, 14.2, 20.2, 19.1)
            ctx.stroke()
        } else if (root.icon === "wifi") {
            ctx.beginPath()
            ctx.arc(12, 17.3, 10.2, Math.PI * 1.20, Math.PI * 1.80)
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(12, 17.5, 6.6, Math.PI * 1.20, Math.PI * 1.80)
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(12, 17.9, 3.0, Math.PI * 1.20, Math.PI * 1.80)
            ctx.stroke()

            ctx.beginPath()
            ctx.arc(12, 18.2, 1.05, 0, Math.PI * 2)
            ctx.fill()
        } else if (root.icon === "keyboard") {
            ctx.strokeRect(3.1, 6.2, 17.8, 11.6)

            for (let row = 0; row < 2; ++row) {
                for (let col = 0; col < 5; ++col) {
                    const x = 5.2 + col * 3.25
                    const y = 9.0 + row * 3.0
                    ctx.beginPath()
                    ctx.arc(x, y, 0.55, 0, Math.PI * 2)
                    ctx.fill()
                }
            }

            ctx.beginPath()
            ctx.moveTo(7.2, 15.3)
            ctx.lineTo(16.8, 15.3)
            ctx.stroke()
        } else if (root.icon === "battery") {
            ctx.strokeRect(3.0, 7.1, 16.5, 9.8)

            ctx.beginPath()
            ctx.moveTo(21.0, 10.0)
            ctx.lineTo(21.0, 14.0)
            ctx.stroke()

            const progress = root.clamp(root.value, 0, 1)
            if (progress > 0) {
                ctx.globalAlpha = 0.90
                ctx.fillRect(5.1, 9.2, 12.3 * progress, 5.6)
                ctx.globalAlpha = 1.0
            }
        }

        ctx.restore()
    }
}
