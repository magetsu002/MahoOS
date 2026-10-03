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

        function poly(ctx, points, closePath) {
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

        function rect(ctx, x, y, w, h) {
            ctx.strokeRect(x, y, w, h)
        }

        function circle(ctx, x, y, r) {
            ctx.beginPath()
            ctx.arc(x, y, r, 0, Math.PI * 2)
            ctx.stroke()
        }

        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.scale(width / 16, height / 16)
            ctx.strokeStyle = root.tone
            ctx.fillStyle = root.tone
            ctx.lineWidth = 0.9
            ctx.lineCap = "butt"
            ctx.lineJoin = "miter"

            const n = root.name.toLowerCase()

            if (n.indexOf("search") >= 0) {
                circle(ctx, 6.6, 6.6, 3.6)
                line(ctx, 9.3, 9.3, 13.2, 13.2)
            } else if (n.indexOf("theme") >= 0 || n.indexOf("appearance") >= 0) {
                circle(ctx, 8, 8, 5.2)
                line(ctx, 8, 1.6, 8, 3.1)
                line(ctx, 8, 12.9, 8, 14.4)
                line(ctx, 1.6, 8, 3.1, 8)
                line(ctx, 12.9, 8, 14.4, 8)
                line(ctx, 3.4, 3.4, 4.5, 4.5)
                line(ctx, 11.5, 11.5, 12.6, 12.6)
                line(ctx, 11.5, 4.5, 12.6, 3.4)
                line(ctx, 3.4, 12.6, 4.5, 11.5)
            } else if (n.indexOf("display") >= 0 || n.indexOf("computer") >= 0) {
                rect(ctx, 2.1, 2.8, 11.8, 7.7)
                line(ctx, 8, 10.5, 8, 13.1)
                line(ctx, 5.2, 13.1, 10.8, 13.1)
            } else if (n.indexOf("volume") >= 0 || n.indexOf("audio") >= 0) {
                poly(ctx, [[2.2,6.2],[5.1,6.2],[8.1,3.7],[8.1,12.3],[5.1,9.8],[2.2,9.8]], true)
                ctx.beginPath()
                ctx.arc(8.0, 8.0, 3.0, -0.75, 0.75)
                ctx.stroke()
            } else if (n.indexOf("microphone") >= 0) {
                rect(ctx, 6, 2.1, 4, 7.2)
                ctx.beginPath()
                ctx.arc(8, 9.1, 4.2, 0, Math.PI)
                ctx.stroke()
                line(ctx, 8, 13.3, 8, 15)
                line(ctx, 5.6, 15, 10.4, 15)
            } else if (n.indexOf("keyboard") >= 0) {
                rect(ctx, 1.5, 3.8, 13, 8.4)
                for (let r = 0; r < 2; ++r)
                    for (let c = 0; c < 5; ++c)
                        rect(ctx, 3 + c * 2.1, 5.4 + r * 2.0, 1.0, 0.8)
                rect(ctx, 4.2, 9.5, 7.6, 0.8)
            } else if (n.indexOf("mouse") >= 0) {
                rect(ctx, 4.5, 1.8, 7, 12.4)
                line(ctx, 8, 1.8, 8, 6.2)
                line(ctx, 4.5, 6.2, 11.5, 6.2)
            } else if (n.indexOf("touchpad") >= 0) {
                rect(ctx, 2, 2.5, 12, 11)
                line(ctx, 2, 10.5, 14, 10.5)
            } else if (n.indexOf("notification") >= 0) {
                poly(ctx, [[3.3,11.1],[4.2,9.8],[4.2,6.4],[4.6,4.3],[6.3,3.0],[8,2.6],[9.7,3.0],[11.4,4.3],[11.8,6.4],[11.8,9.8],[12.7,11.1]], false)
                line(ctx, 3.3, 11.1, 12.7, 11.1)
                ctx.beginPath()
                ctx.arc(8, 11.1, 1.6, 0, Math.PI)
                ctx.stroke()
                if (n.indexOf("disabled") >= 0)
                    line(ctx, 3, 3, 13, 13)
            } else if (n.indexOf("applications") >= 0) {
                for (let r = 0; r < 3; ++r)
                    for (let c = 0; c < 3; ++c)
                        rect(ctx, 2.3 + c * 4.3, 2.3 + r * 4.3, 1.8, 1.8)
            } else if (n.indexOf("internet") >= 0 || n.indexOf("locale") >= 0) {
                circle(ctx, 8, 8, 5.6)
                ctx.beginPath()
                ctx.ellipse(8, 8, 2.5, 5.6, 0, 0, Math.PI * 2)
                ctx.stroke()
                line(ctx, 2.4, 8, 13.6, 8)
            } else if (n.indexOf("time") >= 0 || n.indexOf("appointment") >= 0 || n.indexOf("history") >= 0) {
                circle(ctx, 8, 8, 5.4)
                line(ctx, 8, 4.6, 8, 8.2)
                line(ctx, 8, 8.2, 10.7, 9.8)
            } else if (n.indexOf("shortcut") >= 0) {
                rect(ctx, 1.7, 4, 12.6, 8)
                line(ctx, 4, 6.1, 5.4, 6.1)
                line(ctx, 6.4, 6.1, 7.8, 6.1)
                line(ctx, 8.8, 6.1, 10.2, 6.1)
                line(ctx, 4, 8.3, 5.4, 8.3)
                line(ctx, 6.4, 8.3, 10.2, 8.3)
                line(ctx, 5.4, 10.4, 10.6, 10.4)
            } else if (n.indexOf("windows") >= 0) {
                rect(ctx, 2.2, 2.5, 8.2, 7.4)
                rect(ctx, 5.6, 6.1, 8.2, 7.4)
            } else if (n.indexOf("effects") >= 0) {
                poly(ctx, [[2.2,10.3],[4.7,6.8],[6.9,9.2],[9.2,5.5],[13.8,5.5]], false)
            } else if (n.indexOf("run") >= 0) {
                poly(ctx, [[5,2.5],[12.3,8],[5,13.5]], true)
            } else if (n.indexOf("preferences-system") >= 0 && n.indexOf("notifications") < 0 && n.indexOf("windows") < 0) {
                circle(ctx, 8, 8, 2.5)
                for (let i = 0; i < 8; ++i) {
                    const a = i * Math.PI / 4
                    line(ctx, 8 + Math.cos(a) * 4.0, 8 + Math.sin(a) * 4.0,
                              8 + Math.cos(a) * 5.8, 8 + Math.sin(a) * 5.8)
                }
            } else if (n.indexOf("monitor") >= 0) {
                rect(ctx, 2, 2.2, 12, 11.6)
                poly(ctx, [[3.8,9.3],[5.5,9.3],[6.7,5.5],[8.3,11.0],[9.6,7.4],[12.2,7.4]], false)
            } else if (n.indexOf("about") >= 0 || n.indexOf("help") >= 0) {
                circle(ctx, 8, 8, 5.5)
                line(ctx, 8, 7, 8, 11.2)
                rect(ctx, 7.55, 4.2, 0.9, 0.9)
            } else if (n.indexOf("file-manager") >= 0) {
                poly(ctx, [[1.7,4.1],[6.3,4.1],[7.5,5.2],[14.3,5.2],[13.4,12.6],[2.6,12.6]], true)
            } else if (n.indexOf("image") >= 0) {
                rect(ctx, 2, 2.5, 12, 11)
                poly(ctx, [[3.7,11.2],[6.7,7.8],[8.7,9.8],[10.4,7.8],[12.4,11.2]], false)
                circle(ctx, 10.8, 5.3, 1.0)
            } else if (n.indexOf("battery") >= 0) {
                rect(ctx, 2.2, 5, 10.8, 6)
                line(ctx, 13.1, 6.6, 14.2, 6.6)
                line(ctx, 13.1, 9.4, 14.2, 9.4)
                if (n.indexOf("missing") >= 0)
                    line(ctx, 3.4, 4, 12.6, 12)
            } else {
                rect(ctx, 3.2, 3.2, 9.6, 9.6)
            }
        }
    }
}
