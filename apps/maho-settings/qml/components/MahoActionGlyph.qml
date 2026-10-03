import QtQuick

Item {
    id: root

    property string name: ""
    property color tone: "#f4eeee"

    onNameChanged: canvas.requestPaint()
    onToneChanged: canvas.requestPaint()
    onWidthChanged: canvas.requestPaint()
    onHeightChanged: canvas.requestPaint()

    Canvas {
        id: canvas
        anchors.fill: parent
        antialiasing: true

        function line(ctx, x1, y1, x2, y2) {
            ctx.beginPath()
            ctx.moveTo(x1, y1)
            ctx.lineTo(x2, y2)
            ctx.stroke()
        }

        function polyline(ctx, points, closePath) {
            if (!points || points.length === 0)
                return
            ctx.beginPath()
            ctx.moveTo(points[0][0], points[0][1])
            for (let i = 1; i < points.length; ++i)
                ctx.lineTo(points[i][0], points[i][1])
            if (closePath)
                ctx.closePath()
            ctx.stroke()
        }

        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.scale(width / 16, height / 16)
            ctx.strokeStyle = root.tone
            ctx.fillStyle = root.tone
            ctx.lineWidth = 1.15
            ctx.lineCap = "butt"
            ctx.lineJoin = "miter"

            const n = root.name.toLowerCase()

            if (n.indexOf("add") >= 0 || n.indexOf("plus") >= 0) {
                line(ctx, 8, 3.5, 8, 12.5)
                line(ctx, 3.5, 8, 12.5, 8)
            } else if (n.indexOf("edit") >= 0 || n.indexOf("pencil") >= 0) {
                // Thin open pencil: clearly an edit action without a bulky
                // filled-looking outline at 14px.
                line(ctx, 4.0, 11.8, 10.9, 4.9)
                line(ctx, 5.4, 13.2, 12.3, 6.3)
                line(ctx, 10.9, 4.9, 12.3, 6.3)
                polyline(ctx, [[4.0,11.8],[3.2,13.8],[5.4,13.2]], false)
            } else if (n.indexOf("delete") >= 0 || n.indexOf("trash") >= 0) {
                line(ctx, 3, 4.5, 13, 4.5)
                line(ctx, 6, 2.6, 10, 2.6)
                polyline(ctx, [[4.4,5.3],[5,13.2],[11,13.2],[11.6,5.3]], false)
                line(ctx, 7, 6.5, 7, 11.5)
                line(ctx, 9, 6.5, 9, 11.5)
            } else if (n.indexOf("reset") >= 0 || n.indexOf("restore") >= 0) {
                ctx.beginPath()
                ctx.arc(8, 8, 4.7, -0.35, 4.45)
                ctx.stroke()
                polyline(ctx, [[3.2,4.3],[3.2,8],[6.8,8]], false)
            } else if (n.indexOf("disable") >= 0 || n.indexOf("ban") >= 0) {
                // Distinct from Edit: compact disabled/minus symbol rather
                // than another dominant diagonal stroke.
                ctx.beginPath()
                ctx.arc(8, 8, 4.4, 0, Math.PI * 2)
                ctx.stroke()
                line(ctx, 5.2, 8, 10.8, 8)
            } else if (n.indexOf("focus") >= 0 || n.indexOf("target") >= 0) {
                ctx.beginPath()
                ctx.rect(3.5, 3.5, 9, 9)
                ctx.stroke()
                line(ctx, 8, 1.8, 8, 5)
                line(ctx, 8, 11, 8, 14.2)
                line(ctx, 1.8, 8, 5, 8)
                line(ctx, 11, 8, 14.2, 8)
            } else if (n.indexOf("preview") >= 0 || n.indexOf("eye") >= 0) {
                ctx.beginPath()
                ctx.moveTo(1.8, 8)
                ctx.quadraticCurveTo(8, 2.6, 14.2, 8)
                ctx.quadraticCurveTo(8, 13.4, 1.8, 8)
                ctx.stroke()
                ctx.beginPath()
                ctx.arc(8, 8, 1.8, 0, Math.PI * 2)
                ctx.stroke()
            } else if (n.indexOf("check") >= 0 || n.indexOf("save") >= 0) {
                polyline(ctx, [[2.8,8.2],[6.3,11.4],[13.2,4.6]], false)
            } else if (n.indexOf("close") >= 0 || n.indexOf("cancel") >= 0) {
                line(ctx, 3.7, 3.7, 12.3, 12.3)
                line(ctx, 12.3, 3.7, 3.7, 12.3)
            } else {
                ctx.beginPath()
                ctx.rect(4, 4, 8, 8)
                ctx.stroke()
            }
        }
    }
}
