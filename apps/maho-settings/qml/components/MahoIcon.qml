import QtQuick

Item {
    id: root

    property string name: ""
    property color tone: "#f4eeee"
    property real lineWidth: Math.max(1.2, Math.min(width, height) * 0.075)

    onNameChanged: glyph.requestPaint()
    onToneChanged: glyph.requestPaint()
    onWidthChanged: glyph.requestPaint()
    onHeightChanged: glyph.requestPaint()

    Canvas {
        id: glyph
        anchors.fill: parent
        antialiasing: true

        function path(points, closePath) {
            const ctx = getContext("2d")
            if (!points || points.length === 0)
                return
            ctx.beginPath()
            ctx.moveTo(points[0][0] * width, points[0][1] * height)
            for (let i = 1; i < points.length; ++i)
                ctx.lineTo(points[i][0] * width, points[i][1] * height)
            if (closePath)
                ctx.closePath()
            ctx.stroke()
        }

        function circle(x, y, radius) {
            const ctx = getContext("2d")
            ctx.beginPath()
            ctx.arc(x * width, y * height, radius * Math.min(width, height), 0, Math.PI * 2)
            ctx.stroke()
        }

        function box(x, y, w, h) {
            const ctx = getContext("2d")
            ctx.strokeRect(x * width, y * height, w * width, h * height)
        }

        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = root.tone
            ctx.fillStyle = root.tone
            ctx.lineWidth = root.lineWidth
            ctx.lineCap = "round"
            ctx.lineJoin = "round"

            const n = root.name
            if (n.indexOf("search") >= 0) {
                circle(0.43, 0.43, 0.27)
                path([[0.62, 0.62], [0.86, 0.86]], false)
            } else if (n.indexOf("display") >= 0 || n.indexOf("video") >= 0) {
                box(0.10, 0.16, 0.80, 0.56)
                path([[0.50,0.72],[0.50,0.86],[0.35,0.86],[0.65,0.86]], false)
            } else if (n.indexOf("audio") >= 0 || n.indexOf("volume") >= 0) {
                path([[0.12,0.42],[0.31,0.42],[0.52,0.24],[0.52,0.76],[0.31,0.58],[0.12,0.58]], true)
                ctx.beginPath(); ctx.arc(0.52*width,0.50*height,0.22*Math.min(width,height),-0.78,0.78); ctx.stroke()
                ctx.beginPath(); ctx.arc(0.52*width,0.50*height,0.34*Math.min(width,height),-0.66,0.66); ctx.stroke()
            } else if (n.indexOf("keyboard") >= 0) {
                box(0.08,0.23,0.84,0.56)
                for (let row=0; row<2; ++row) for (let col=0; col<5; ++col) {
                    ctx.beginPath(); ctx.arc((0.20+col*0.15)*width,(0.39+row*0.15)*height,root.lineWidth*0.52,0,Math.PI*2); ctx.fill()
                }
                path([[0.28,0.69],[0.72,0.69]], false)
            } else if (n.indexOf("battery") >= 0 || n.indexOf("power") >= 0) {
                box(0.11,0.29,0.68,0.42)
                path([[0.84,0.41],[0.84,0.59]], false)
                path([[0.43,0.35],[0.35,0.52],[0.49,0.52],[0.42,0.66]], false)
            } else if (n.indexOf("notification") >= 0 || n.indexOf("bell") >= 0) {
                ctx.beginPath()
                ctx.moveTo(0.22*width,0.69*height)
                ctx.quadraticCurveTo(0.31*width,0.60*height,0.31*width,0.39*height)
                ctx.quadraticCurveTo(0.31*width,0.18*height,0.50*width,0.18*height)
                ctx.quadraticCurveTo(0.69*width,0.18*height,0.69*width,0.39*height)
                ctx.quadraticCurveTo(0.69*width,0.60*height,0.78*width,0.69*height)
                ctx.closePath(); ctx.stroke()
                ctx.beginPath(); ctx.arc(0.50*width,0.72*height,0.09*Math.min(width,height),0,Math.PI); ctx.stroke()
            } else if (n.indexOf("applications") >= 0 || n.indexOf("grid") >= 0) {
                for (let row=0; row<3; ++row) for (let col=0; col<3; ++col) {
                    ctx.beginPath(); ctx.arc((0.25+col*0.25)*width,(0.25+row*0.25)*height,0.04*Math.min(width,height),0,Math.PI*2); ctx.fill()
                }
            } else if (n.indexOf("locale") >= 0 || n.indexOf("region") >= 0 || n.indexOf("globe") >= 0) {
                circle(0.50,0.50,0.37)
                ctx.beginPath(); ctx.ellipse(0.50*width,0.50*height,0.18*width,0.37*height,0,0,Math.PI*2); ctx.stroke()
                path([[0.15,0.50],[0.85,0.50]], false)
            } else if (n.indexOf("theme") >= 0 || n.indexOf("appearance") >= 0) {
                circle(0.47,0.48,0.33)
                const dots=[[0.29,0.38],[0.43,0.28],[0.61,0.34]]
                for (const d of dots) { ctx.beginPath(); ctx.arc(d[0]*width,d[1]*height,0.035*Math.min(width,height),0,Math.PI*2); ctx.fill() }
            } else if (n.indexOf("windows") >= 0 || n.indexOf("rules") >= 0) {
                box(0.12,0.16,0.62,0.52)
                box(0.29,0.31,0.59,0.53)
            } else if (n.indexOf("effects") >= 0 || n.indexOf("motion") >= 0) {
                ctx.beginPath()
                ctx.moveTo(0.08*width,0.59*height)
                ctx.bezierCurveTo(0.25*width,0.12*height,0.37*width,0.87*height,0.51*width,0.43*height)
                ctx.bezierCurveTo(0.67*width,0.00*height,0.75*width,0.82*height,0.92*width,0.36*height)
                ctx.stroke()
            } else if (n.indexOf("run") >= 0 || n.indexOf("session") >= 0) {
                path([[0.27,0.17],[0.78,0.50],[0.27,0.83]], true)
            } else if (n.indexOf("monitor") >= 0 || n.indexOf("diagnostic") >= 0) {
                box(0.12,0.12,0.76,0.76)
                path([[0.20,0.57],[0.34,0.57],[0.43,0.35],[0.55,0.68],[0.63,0.48],[0.80,0.48]], false)
            } else if (n.indexOf("about") >= 0 || n.indexOf("help") >= 0) {
                circle(0.50,0.50,0.37)
                path([[0.50,0.46],[0.50,0.70]], false)
                ctx.beginPath(); ctx.arc(0.50*width,0.31*height,0.04*Math.min(width,height),0,Math.PI*2); ctx.fill()
            } else if (n.indexOf("system") >= 0 || n.indexOf("config") >= 0) {
                circle(0.50,0.50,0.19)
                for (let i=0; i<8; ++i) {
                    const a=i*Math.PI/4
                    path([[0.50+Math.cos(a)*0.27,0.50+Math.sin(a)*0.27],[0.50+Math.cos(a)*0.39,0.50+Math.sin(a)*0.39]], false)
                }
            } else {
                circle(0.50,0.50,0.31)
            }
        }
    }
}
