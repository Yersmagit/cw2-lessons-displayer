import QtQuick 2.15

// 线型预览（Canvas 自绘）：把一种线型直接画出来。
// 参数与 Python 侧 _draw_shape_line 一一对应，由「形状菜单·线」与「浮动工具栏·线型菜单」
// 共用（避免两处参数各自漂移）。线型 id：
//   line 直线 / dash 虚线(划 1.6w、间隔 3.6w，RoundCap 后视觉各约 2.6w) /
//   dashdot 点虚线(长划 2.2w、间隔 3.2w、正圆点) / wave 波浪线(振幅 0.5w、波长 4w) /
//   dot 点状虚线(圆点直径 w、间距 2.2w) / double 双实线(各 0.45w、法向偏移 0.5w) /
//   arrow 箭头(实线 + 终点 V 形箭头) / dblarrow 双向箭头(两端各一个) /
//   ray 光线(沿线均匀分布的 V 形箭头，数量 ∝ 线长) /
//   hatch 剖面线(实线 + 右侧一组 45° 平行梳齿)
Canvas {
    id: root
    property string styleId: ""
    property real lineWidth: 3
    property color lineColor: "#000000"

    onStyleIdChanged: requestPaint()
    onLineWidthChanged: requestPaint()
    onLineColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Component.onCompleted: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        var lw = Math.max(1, root.lineWidth)
        var sid = root.styleId
        var y = height / 2
        var x0 = lw * 0.5 + 1
        var x1 = width - lw * 0.5 - 1
        if (x1 <= x0) return
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.strokeStyle = root.lineColor
        ctx.fillStyle = root.lineColor

        if (sid === "line") {
            // 直线：均匀粗细实线
            ctx.lineWidth = lw
            ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke()
        } else if (sid === "dot") {
            // 点状虚线：每个循环节一个圆（直径 = 线宽，间距 2.2×线宽）
            var gap = lw * 2.2
            var n = Math.max(1, Math.floor((x1 - x0) / gap))
            for (var i = 0; i <= n; i++) {
                ctx.beginPath()
                ctx.arc(x0 + i * gap, y, lw / 2, 0, Math.PI * 2)
                ctx.fill()
            }
        } else if (sid === "wave") {
            // 波浪线：正弦（振幅 0.5×线宽、波长 4×线宽）
            var amp = lw * 0.5
            var wl = Math.max(10, lw * 4)
            ctx.lineWidth = lw
            ctx.beginPath()
            for (var x = x0; x <= x1; x += 1) {
                var yy = y + Math.sin(2 * Math.PI * (x - x0) / wl) * amp
                if (x === x0) ctx.moveTo(x, yy)
                else ctx.lineTo(x, yy)
            }
            ctx.stroke()
        } else if (sid === "double") {
            // 双实线：两条平行线（各 0.45×线宽，法向偏移 0.5×线宽）
            var off = Math.max(1.2, lw * 0.5)
            ctx.lineWidth = Math.max(1, lw * 0.45)
            ctx.beginPath(); ctx.moveTo(x0, y - off); ctx.lineTo(x1, y - off); ctx.stroke()
            ctx.beginPath(); ctx.moveTo(x0, y + off); ctx.lineTo(x1, y + off); ctx.stroke()
        } else if (sid === "arrow" || sid === "dblarrow" || sid === "ray") {
            // 箭头 / 双向箭头 / 光线：实线 + V 形箭头（与 Python _draw_arrow_head 同参：
            // 臂长 max(6, 2.5w)、半角 30°，尖端落在线上）
            ctx.lineWidth = lw
            ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke()
            var hl = Math.max(6, lw * 2.5)
            var bl = hl * Math.cos(Math.PI / 6)
            var sl = hl * Math.sin(Math.PI / 6)
            if (sid === "arrow" || sid === "dblarrow") {
                // 终点箭头指向 +x；双向箭头再在起点加一个指向 −x 的
                ctx.beginPath()
                ctx.moveTo(x1 - bl, y - sl); ctx.lineTo(x1, y); ctx.lineTo(x1 - bl, y + sl)
                ctx.stroke()
                if (sid === "dblarrow") {
                    ctx.beginPath()
                    ctx.moveTo(x0 + bl, y - sl); ctx.lineTo(x0, y); ctx.lineTo(x0 + bl, y + sl)
                    ctx.stroke()
                }
            } else {
                // 光线：数量与线长正相关 n = max(1, ⌊L/间距⌋)，间距 max(80, 24w)，
                // 第 i 个放在第 i 段中心 → 短线的 1 个正好在中点，且始终均匀对称
                var step = Math.max(80, lw * 24)
                var nr = Math.max(1, Math.floor((x1 - x0) / step))
                for (var ir = 0; ir < nr; ir++) {
                    var cxr = x0 + (x1 - x0) * (ir + 0.5) / nr
                    ctx.beginPath()
                    ctx.moveTo(cxr - bl, y - sl); ctx.lineTo(cxr, y); ctx.lineTo(cxr - bl, y + sl)
                    ctx.stroke()
                }
            }
        } else if (sid === "hatch") {
            // 剖面线：实线 + 一侧一组平行梳齿（每根与主线 45°，在"由起点看向终点"的右侧；
            // 预览里线由左向右 → 右侧即屏幕下方 +y，所以梳齿朝左下）
            ctx.lineWidth = lw
            ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.stroke()
            var tl = Math.max(4, lw * 2)
            var gapH = Math.max(5, lw * 2.5)
            var nh = Math.max(1, Math.floor((x1 - x0) / gapH))
            var hdx = -Math.SQRT1_2
            var hdy = Math.SQRT1_2
            for (var ih = 0; ih < nh; ih++) {
                var pxh = x0 + (x1 - x0) * (ih + 0.5) / nh
                ctx.beginPath()
                ctx.moveTo(pxh, y); ctx.lineTo(pxh + hdx * tl, y + hdy * tl)
                ctx.stroke()
            }
        } else if (sid === "dashdot") {
            // 点虚线：长划 + 正圆点（圆点显式画圆，不依赖 Canvas 对零长度段的处理）
            ctx.lineWidth = lw
            var dashLen = lw * 2.2
            var gapD = lw * 3.2
            var cx2 = x0
            while (cx2 < x1) {
                var e2 = Math.min(x1, cx2 + dashLen)
                ctx.beginPath(); ctx.moveTo(cx2, y); ctx.lineTo(e2, y); ctx.stroke()
                var dotC = e2 + gapD + lw / 2
                if (dotC + lw / 2 < x1) {
                    ctx.beginPath(); ctx.arc(dotC, y, lw / 2, 0, Math.PI * 2); ctx.fill()
                }
                cx2 = dotC + lw / 2 + gapD
            }
        } else {
            // 虚线：手动分段（不依赖 setLineDash 语义）
            ctx.lineWidth = lw
            var on = lw * 1.6
            var off2 = lw * 3.6
            var cx = x0
            while (cx < x1) {
                var e = Math.min(x1, cx + on)
                ctx.beginPath(); ctx.moveTo(cx, y); ctx.lineTo(e, y); ctx.stroke()
                cx = e + off2
            }
        }
    }
}
