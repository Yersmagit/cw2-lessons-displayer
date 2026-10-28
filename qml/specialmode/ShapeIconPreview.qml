import QtQuick 2.15

// 图形预览（Canvas 自绘）：把"图形"菜单里的一种图形直接画出来。
// 顶点公式与 Python 侧 _figure_unit_polygon 一一对应（三角形/矩形/直角三角为直观内接；
// 五/六/八边形/星形取单位轮廓后把其包围盒仿射映射到目标框 → 方框比例与等边比
// 例一致时即正多边形/正星形）。
// 朝向：六边形第一个顶点朝右（平顶）→ 上、下两条对边**横着**；八边形起始 22.5°
// → 上/下是水平边、左/右是竖直边；星形（五角星）一角朝上；圆以短边内接（正圆）；
// 椭圆：中心在框中心、半长轴 = 短边/2 − pad、半短轴 = 0.78 * 半长轴，并画出**两个焦点**
// （与 Python 侧 _ellipse_outline 同一套构造）；半短轴比例与轮廓是否画虚线可用
// ellipsePlump / ellipseDashed 调（提示胶囊里的小椭圆用更饱满的 0.88 + 虚线）。
// 扇形：圆心在左下角、半径 = 短边 − 2px、圆心角 90°（与 Python 侧 _sector_figure_points 同构造）。
// 多边形随心画：用户手画的那一个（5 顶点：底边 → 右侧 → 左上尖角 → 左侧内凹角，
// 与 Python 侧 _figure_unit_polygon("polfree") 同一套顶点）。
// **立体图形小图（triprism 三棱柱 / quadprism 四棱柱）**：斜二测画法的小图 —— 底面
// （底面平面里图形的**投影**）+ 顶面 + **被遮挡棱**。菜单小图里被遮挡棱一律用**点状虚线**
// （与双曲线小图的渐近线同一套画法）便于阅读；**实际绘制到画布上的虚线样式不变**（用户要求）。
// 另外还有两个**提示专用**小图标："pfeq"（等于号 =）、"pfpara"（平行标记 ∥）。
Canvas {
    id: root
    property string kind: ""            // tri / rtri / rect / pent / hex / oct / star / circle / ellipse ...
    property color lineColor: "#000000"
    property real lineWidth: 2
    // 椭圆参数（默认值 = 图形菜单里的画法；提示胶囊会传更饱满 / 虚线）：
    property real ellipsePlump: 0.78    // 半短轴 / 半长轴
    property bool ellipseDashed: false  // 轮廓画成虚线（Qt Canvas 的 setLineDash 不可靠 → 手动按弧长分段）
    // 立体图形的**测画方式**（只影响同时支持两种的图形，目前是圆柱）：
    //   "iso" = 正等测（默认，与 Python 侧 `_SOLID_PROJ_DEFAULT` 一致）、"oblique" = 斜二测
    property string projMode: "iso"
    // 五角星内圈/外圈半径比 = cos72°/cos36° ≈ 0.38197（与 Python 侧同值）
    readonly property real starInnerRatio: 0.3819660112501051
    // 正多边形/正星形"等边"所需的辅助矩形长宽比（= Python 侧 _figure_aspect 的镜像副本）：
    // 三角形/六边形 = 2/sqrt(3)、矩形/八边形 = 1、五边形/星形 = 单位轮廓包围盒比例 ≈ 1.05146。
    // 菜单格子是 26x24（长宽比 ≠ 图形比例），把单位轮廓直接映射到格子会被拉伸成非正多边形 →
    // 下面 loopPoints 先取"格内最大等比子框"（居中）再映射，保证小图永远是标准正多边形/正星形。
    readonly property var regularAspect: ({
        "tri": 2.0 / Math.sqrt(3.0),
        "rtri": 1.0,
        "rect": 1.0,
        "pent": 1.0514622242382672,
        "hex": 2.0 / Math.sqrt(3.0),
        "oct": 1.0,
        "star": 1.0514622242382672
    })

    onKindChanged: requestPaint()
    onLineColorChanged: requestPaint()
    onLineWidthChanged: requestPaint()
    onProjModeChanged: requestPaint()
    onEllipsePlumpChanged: requestPaint()
    onEllipseDashedChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    Component.onCompleted: requestPaint()

    // 由"辅助矩形"得到图形轮廓（闭合点列）
    function loopPoints(k, x0, y0, x1, y1) {
        var l = Math.min(x0, x1), r = Math.max(x0, x1)
        var t = Math.min(y0, y1), b = Math.max(y0, y1)
        // 正多边形/正星形：先在框内取"最大等比子框"（居中）→ 小图永远是标准正多边形/正星形
        var asp = root.regularAspect[k]
        if (asp !== undefined) {
            var bw = r - l, bh = b - t
            var fw = Math.min(bw, bh * asp)
            var fh = fw / asp
            l = l + (bw - fw) / 2
            t = t + (bh - fh) / 2
            r = l + fw
            b = t + fh
        }
        var cx = (l + r) / 2
        var loop = []
        if (k === "rect") {
            loop = [[l, t], [r, t], [r, b], [l, b]]
        } else if (k === "tri") {
            loop = [[cx, t], [r, b], [l, b]]
        } else {
            // 单位轮廓（外接圆半径 1，与 Python 侧 _figure_unit_polygon 完全一致）
            var raw = []
            var direct = false          // true = raw 已是绝对坐标（扇形），无需按包围盒映射
            if (k === "star") {
                // 五角星：一角朝上，外圈 5 个尖角 + 内圈 5 个凹角交替（10 个顶点）
                var ir = root.starInnerRatio
                for (var s = 0; s < 5; s++) {
                    var a1 = (-90 + 72 * s) * Math.PI / 180
                    raw.push([Math.cos(a1), Math.sin(a1)])
                    var a2 = (-90 + 72 * s + 36) * Math.PI / 180
                    raw.push([Math.cos(a2) * ir, Math.sin(a2) * ir])
                }
            } else if (k === "rtri" || k === "rtri30" || k === "rtri45" || k === "rtri60") {
                // 直角三角（含提示胶囊的 30°/45°/60° 三个伪 id）：**直角顶点在左下角**，
                // 两条直角边 = 底边（横）+ 左边（竖）→ 斜边自右下向左上。
                // 方框 1:1 → 等腰直角三角形；提示胶囊按 shapeAspects 给框，
                // 框长宽比不同时就是 30°（扁）/ 60°（瘦）直角三角形。
                raw = [[0, 1], [1, 1], [0, 0]]
            } else if (k === "sector" || k === "sector2") {
                // 扇形（含第二阶段的伪 id "sector2"）：圆心在**左下角**、半径 = 短边 − 2px、
                // 圆心角 90°（第一条半径朝右、逆时针 90° 到朝上）。
                // ⚠️ 段数 33 与 Python 侧 `_sector_figure_points`（|sweep|/360 × 128 + 1）
                // 保持一致，菜单小图与 Python 参考渲染逐像素可比。
                var sd = Math.max(2, Math.min(r - l, b - t) - 2)
                var vx0 = l + 1, vy0 = b - 1
                raw = [[vx0 + sd, vy0]]
                for (var si = 1; si <= 33; si++) {
                    var sa = (-90 * si / 33) * Math.PI / 180
                    raw.push([vx0 + sd * Math.cos(sa), vy0 + sd * Math.sin(sa)])
                }
                raw.push([vx0, vy0])              // 回到圆心（第二条半径）
                direct = true                     // 已是绝对坐标；闭合点仍由下面统一补
            } else if (k === "polfree") {
                // 多边形随心画：**用户手画的那一个**（5 顶点，含左侧内凹角）——与 Python 侧
                // _figure_unit_polygon("polfree") 同一套顶点；按包围盒映射到方框
                raw = [[0.2042, 1.0], [0.7538, 1.0], [1.0, 0.5303], [0.0, 0.0], [0.3016, 0.4867]]
            } else {
                // 五边形尖顶（-90°）；六边形平顶（0°）；八边形平顶平边（22.5°）
                var n = (k === "pent") ? 5 : ((k === "oct") ? 8 : 6)
                var startDeg = (k === "pent") ? -90 : ((k === "oct") ? 22.5 : 0)
                for (var i = 0; i < n; i++) {
                    var a = (startDeg + 360 * i / n) * Math.PI / 180
                    raw.push([Math.cos(a), Math.sin(a)])
                }
            }
            if (direct) {
                loop = raw
            } else {
                var m = raw.length
                var mnx = 1e9, mxx = -1e9, mny = 1e9, mxy = -1e9
                for (var q = 0; q < m; q++) {
                    mnx = Math.min(mnx, raw[q][0]); mxx = Math.max(mxx, raw[q][0])
                    mny = Math.min(mny, raw[q][1]); mxy = Math.max(mxy, raw[q][1])
                }
                var scx = (mxx - mnx) > 1e-9 ? (r - l) / (mxx - mnx) : 1
                var scy = (mxy - mny) > 1e-9 ? (b - t) / (mxy - mny) : 1
                for (var j = 0; j < m; j++) {
                    loop.push([l + (raw[j][0] - mnx) * scx, t + (raw[j][1] - mny) * scy])
                }
            }
        }
        loop.push([loop[0][0], loop[0][1]])   // 闭合（首尾同点）
        return loop
    }

    // 闭合点列画虚线：按**弧长**参数化逐段手工画（Qt Canvas 的 setLineDash 在部分
    // 后端不可靠；与 SnapHint 的虚线胶囊边框同一套做法）
    function dashedLoop(ctx, pts, dash, gap) {
        var n = pts.length
        if (n < 2) return
        var lens = []
        var total = 0
        for (var i = 1; i < n; i++) {
            var len = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
            lens.push(len)
            total += len
        }
        if (total <= 1e-6) return
        function pointAt(s) {
            var acc = 0
            for (var j = 1; j < n; j++) {
                var sj = lens[j - 1]
                if (s <= acc + sj || j === n - 1) {
                    var t = Math.max(0, Math.min(1, (s - acc) / Math.max(1e-9, sj)))
                    return [pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * t,
                            pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * t]
                }
                acc += sj
            }
            return pts[n - 1]
        }
        ctx.beginPath()
        var pos = 0
        while (pos < total) {
            var end = Math.min(total, pos + dash)
            var a = pointAt(pos)
            var b = pointAt(end)
            ctx.moveTo(a[0], a[1])
            ctx.lineTo(b[0], b[1])
            pos = end + gap
        }
        ctx.stroke()
    }

    // 闭合/折线点列画**点状虚线**：沿弧长等距画小圆点（与形状菜单"点状虚线"同风格：
    // 直径 = 线宽、间距 2.2 倍线宽）。双曲线小图的渐近线用它 —— 比短划虚线更易读。
    function dottedPolyline(ctx, pts, dotR, spacing) {
        var n = pts.length
        if (n < 2) return
        var lens = []
        var total = 0
        for (var i = 1; i < n; i++) {
            var len = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
            lens.push(len)
            total += len
        }
        if (total <= 1e-6) return
        function pointAt(s) {
            var acc = 0
            for (var j = 1; j < n; j++) {
                var sj = lens[j - 1]
                if (s <= acc + sj || j === n - 1) {
                    var t = Math.max(0, Math.min(1, (s - acc) / Math.max(1e-9, sj)))
                    return [pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * t,
                            pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * t]
                }
                acc += sj
            }
            return pts[n - 1]
        }
        ctx.beginPath()
        for (var s = 0; s <= total; s += spacing) {
            var p = pointAt(s)
            ctx.moveTo(p[0] + dotR, p[1])      // 断开子路径，避免圆点被连成线
            ctx.arc(p[0], p[1], dotR, 0, Math.PI * 2)
        }
        ctx.fill()
    }

    onPaint: {
        var ctx = getContext("2d")
        ctx.clearRect(0, 0, width, height)
        if (!root.kind || width < 6 || height < 6) return
        var lw = Math.max(1, root.lineWidth)
        var pad = lw / 2 + 1
        ctx.lineWidth = lw
        ctx.lineJoin = "round"
        ctx.lineCap = "round"
        ctx.strokeStyle = root.lineColor
        if (root.kind === "circle") {
            // 圆：以短边为准内接（与 Python 侧 _figure_points 一致：圆心在框中心、
            // 半径 = 短边/2 − pad）→ 格子不是正方形时也是正圆；
            // **并画出圆心点**（与真实绘制 _draw_shape_line 一致：半径 = max(1.5, 笔宽/2)）
            var cr = Math.max(1, Math.min(width, height) / 2 - pad)
            ctx.beginPath()
            ctx.arc(width / 2, height / 2, cr, 0, Math.PI * 2)
            ctx.stroke()
            ctx.beginPath()
            ctx.arc(width / 2, height / 2, Math.max(1.5, lw / 2), 0, Math.PI * 2)
            ctx.fillStyle = root.lineColor
            ctx.fill()
            return
        }
        if (root.kind === "ellipse" || root.kind === "ellipse2") {
            // 椭圆（ellipse = 第一阶段提示"焦点"；ellipse2 = 第二阶段提示"双焦半径"，同一个小图标）：
            // 中心在框中心、半长轴 a = 短边/2 − pad、半短轴 b = 0.78a（比初版的 0.62a
            // 饱满一些，用户要求；同时两焦点仍在框内、椭圆明显不是圆）；
            // 与圆一样把**两焦点**画成小圆点（用户要求图形包含两焦点）。
            // 轮廓用 128 段折线画（**不用 ctx.ellipse**：Qt 的 Canvas 对 ellipse() 参数解释
            // 与 W3C 不一致 —— 实测按"左上角 + 宽高"解释，画出来跑到右下角；折线还能与
            // Python 侧 _ellipse_outline 逐像素对齐）；需要虚线时按弧长手工分段。
            var ea = Math.max(3, Math.min(width, height) / 2 - pad)
            var eb = ea * root.ellipsePlump
            var ec = Math.sqrt(Math.max(0, ea * ea - eb * eb))
            var dotR = Math.max(1.5, lw / 2)
            var seg = 128
            var loopE = []
            for (var i = 0; i <= seg; i++) {
                var t = 2 * Math.PI * i / seg
                loopE.push([width / 2 + ea * Math.cos(t), height / 2 + eb * Math.sin(t)])
            }
            if (root.ellipseDashed) {
                dashedLoop(ctx, loopE, Math.max(2.5, lw * 2), Math.max(1.8, lw * 1.5))
            } else {
                ctx.beginPath()
                ctx.moveTo(loopE[0][0], loopE[0][1])
                for (var k = 1; k < loopE.length; k++) ctx.lineTo(loopE[k][0], loopE[k][1])
                ctx.stroke()
            }
            ctx.beginPath()
            ctx.arc(width / 2 - ec, height / 2, dotR, 0, Math.PI * 2)
            ctx.fillStyle = root.lineColor
            ctx.fill()
            ctx.beginPath()
            ctx.arc(width / 2 + ec, height / 2, dotR, 0, Math.PI * 2)
            ctx.fill()
            return
        }
        if (root.kind === "hyp" || root.kind === "hypas") {
            // 双曲线图标：实轴水平、渐近线 45°（与后端 _hyp_branch_points / _hyp_asymptote_points
            // 同一套双曲参数化）；**支线实线、渐近线虚线**（虚线手工按弧长分段）。
            // kind = "hyp"    → 完整双曲线（两支 + 两条渐近线 + 两焦点），形状菜单用；
            // kind = "hypas"  → 只画两条渐近线（交叉的 X），吸附提示"渐近线"用。
            var hW = width / 2 - pad
            var hH = height / 2 - pad
            var hS = 1.0                                   // 渐近线斜率 b/a
            var hX = Math.min(hW, hH / hS)                 // 渐近线的绘制范围（局部实轴半长）
            // 顶点取 0.65X（初版 0.34X 太靠里 → 焦点会贴在支线顶点上）：
            // 切线转角仍有 ~38°，同时**焦点与顶点、支线与渐近线**都拉开（用户要求“离得远、易读”）
            var hA = Math.max(1.5, hX * 0.65)
            var hB = hA * hS
            var hC = Math.sqrt(hA * hA + hB * hB)
            // 渐近线用**点状虚线**（比短划虚线在小图上更易读）
            var hDotR = Math.max(0.8, lw / 2)
            var hSpace = Math.max(3.0, lw * 2.2)
            var cxh = width / 2
            var cyh = height / 2
            var dyh = hB / hA * hX
            ctx.fillStyle = root.lineColor                  // 点状虚线用 fill 画圆点
            dottedPolyline(ctx, [[cxh - hX, cyh - dyh], [cxh + hX, cyh + dyh]], hDotR, hSpace)
            dottedPolyline(ctx, [[cxh - hX, cyh + dyh], [cxh + hX, cyh - dyh]], hDotR, hSpace)
            if (root.kind === "hypas") return               // 提示胶囊只需表示"渐近线"
            // 支线画到与渐近线**同一 x**（X）：两条的截断位置尽量靠近（只差渐近线固有的
            // 纵向间距 s·a²/2X ≈ 0.2X），而不是像初版那样只画到 0.85X 而显出一副“被剪短”的样子
            var hXb = hX
            var hRatio = hXb / hA
            var hT = Math.log(hRatio + Math.sqrt(Math.max(0, hRatio * hRatio - 1)))
            var hN = 24
            for (var hSide = 1; hSide >= -1; hSide -= 2) {
                var hPts = []
                for (var h1 = 0; h1 <= hN; h1++) {
                    var ht1 = hT * (1 - h1 / hN)
                    hPts.push([cxh + hSide * hA * Math.cosh(ht1), cyh + hB * Math.sinh(ht1)])
                }
                for (var h2 = 1; h2 <= hN; h2++) {
                    var ht2 = hT * h2 / hN
                    hPts.push([cxh + hSide * hA * Math.cosh(ht2), cyh - hB * Math.sinh(ht2)])
                }
                ctx.beginPath()
                ctx.moveTo(hPts[0][0], hPts[0][1])
                for (var h3 = 1; h3 < hPts.length; h3++) ctx.lineTo(hPts[h3][0], hPts[h3][1])
                ctx.stroke()
            }
            var hDotFr = Math.max(1.3, lw * 0.6)
            ctx.fillStyle = root.lineColor
            ctx.beginPath()
            ctx.arc(cxh - hC, cyh, hDotFr, 0, Math.PI * 2)
            ctx.fill()
            ctx.beginPath()
            ctx.arc(cxh + hC, cyh, hDotFr, 0, Math.PI * 2)
            ctx.fill()
            return
        }
        if (root.kind === "para") {
            // 抛物线小图：局部坐标（原点 = 顶点、x 沿对称轴向右、y 沿法向）：y^2 = 4px。
            // 与 Python 侧 _parabola_params / _parabola_curve_points 同一套公式：
            // 曲线画到 x = 2p（= 焦准距），末端 |y| = 2*sqrt(2)*p；
            // 准线 = 过顶点左侧 p 处、垂直于对称轴的直线（点状虚线，同双曲线小图的渐近线风格）；
            // 焦点（头部点）画成小圆点。整个图形在框内水平/垂直居中。
            var pfW = Math.max(2, width - 2 * pad)
            var pfH = Math.max(2, height - 2 * pad)
            var pp = Math.min(pfW / 3.0, pfH / (4.0 * Math.SQRT2))
            var pvx = (width - 3.0 * pp) / 2.0 + pp
            var pvy = height / 2
            var pM = Math.SQRT2                      // m 上限 = sqrt(X/p) = sqrt(2)
            var pN = 40
            ctx.beginPath()
            for (var p1 = 0; p1 <= pN; p1++) {
                var pm = -pM + 2 * pM * p1 / pN
                var px = pvx + pp * pm * pm
                var py = pvy + 2 * pp * pm
                if (p1 === 0) ctx.moveTo(px, py)
                else ctx.lineTo(px, py)
            }
            ctx.stroke()
            var pHalf = 2 * Math.SQRT2 * pp          // 准线半长 = 曲线末端 |y|
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[pvx - pp, pvy - pHalf], [pvx - pp, pvy + pHalf]],
                           Math.max(0.8, lw / 2), Math.max(3.0, lw * 2.2))
            ctx.beginPath()
            ctx.arc(pvx + pp, pvy, Math.max(1.3, lw * 0.6), 0, Math.PI * 2)
            ctx.fill()
            return
        }
        if (root.kind === "para2") {
            // 提示"焦准距线段"：准线（点状虚线竖线）+ 焦准距线段（实线横线）+ 焦点（圆点）
            // （与 "hypas" 只画渐近线同理：只画这个提示关心的要素，不画曲线）
            var p2r = Math.max(1.3, lw * 0.6)
            var p2y = height / 2
            var p2x = pad
            var p2fx = width - pad - p2r          // 焦点（线段右端）
            ctx.beginPath()
            ctx.moveTo(p2x, p2y)
            ctx.lineTo(p2fx, p2y)
            ctx.stroke()
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[p2x, pad], [p2x, height - pad]],
                           Math.max(0.8, lw / 2), Math.max(3.0, lw * 2.2))
            ctx.beginPath()
            ctx.arc(p2fx, p2y, p2r, 0, Math.PI * 2)
            ctx.fill()
            return
        }
        if (root.kind === "alignh" || root.kind === "alignv") {
            // 横平竖直吸附提示的小图标：**两个指向两侧的小箭头**
            // （alignh = 左右两侧 ←→；alignv = 上下两侧 ^v）——中间一条细线 + 两端箭头
            var aHoriz = root.kind === "alignh"
            var arm = Math.max(2.2, lw * 1.6)                 // 箭头臂长
            var cx0 = width / 2, cy0 = height / 2
            var aLen = Math.max(4, (aHoriz ? width : height) - 2 * pad - 2)
            var x0 = aHoriz ? cx0 - aLen / 2 : cx0
            var y0 = aHoriz ? cy0 : cy0 - aLen / 2
            var x1 = aHoriz ? cx0 + aLen / 2 : cx0
            var y1 = aHoriz ? cy0 : cy0 + aLen / 2
            ctx.beginPath()
            ctx.moveTo(x0, y0)
            ctx.lineTo(x1, y1)
            if (aHoriz) {
                ctx.moveTo(x0 + arm, y0 - arm)
                ctx.lineTo(x0, y0)
                ctx.lineTo(x0 + arm, y0 + arm)
                ctx.moveTo(x1 - arm, y1 - arm)
                ctx.lineTo(x1, y1)
                ctx.lineTo(x1 - arm, y1 + arm)
            } else {
                ctx.moveTo(x0 - arm, y0 + arm)
                ctx.lineTo(x0, y0)
                ctx.lineTo(x0 + arm, y0 + arm)
                ctx.moveTo(x1 - arm, y1 - arm)
                ctx.lineTo(x1, y1)
                ctx.lineTo(x1 + arm, y1 - arm)
            }
            ctx.stroke()
            return
        }
        if (root.kind === "pfeq" || root.kind === "pfpara") {
            // 多边形随心画的等长/平行吸附小图标：**等于号 "="** / **平行标记 "∥"**
            // （与 _render_menu.py 里的参考几何一一对应：等于号两条横线、平行标记两条斜线）
            ctx.beginPath()
            if (root.kind === "pfeq") {
                var eqX0 = pad + 1, eqX1 = width - pad - 1
                ctx.moveTo(eqX0, height * 0.36)
                ctx.lineTo(eqX1, height * 0.36)
                ctx.moveTo(eqX0, height * 0.64)
                ctx.lineTo(eqX1, height * 0.64)
            } else {
                var pTop = pad + 1, pBot = height - pad - 1
                var ds = Math.max(2.0, width * 0.16)   // 斜度（平行标记是斜着画的两条平行线）
                var pa = width * 0.56, pb = width * 0.84
                ctx.moveTo(pa, pTop)
                ctx.lineTo(pa - ds, pBot)
                ctx.moveTo(pb, pTop)
                ctx.lineTo(pb - ds, pBot)
            }
            ctx.stroke()
            return
        }
        if (root.kind === "triprism") {
            // 三棱柱小图：**斜二测画法**（与 Python 侧 `_solid_base_pts` + `_solid_strokes`
            // 同一套结果 —— 底面是"底面平面里等腰三角形"的**投影**，所以看起来扁而斜）。
            // 底面：拖拽（起点→终点）是底面平面矩形的**一条对角线**；矩形两组对边分别沿 y 轴
            // （纸面水平、1:1）与 x 轴（纸面 45°、折半）→ 投影后是一个平行四边形。
            // 底边 = 与终点相邻的那条 y 边；顶点 = 其对边（另一条 y 边）的中点。
            // 等边配置：V = U·k/(asp-k)；升维高度 H = U+V（≈ 底面边长）。
            var kk = 0.5 * Math.cos(Math.PI / 4)          // 斜二测系数 k = 0.35355
            var asp = 2 / Math.sqrt(3)                    // 等边：底边 / 高
            var cV = kk / (asp - kk)                      // V/U（等边时）
            var aw = Math.max(4, width - 2 * pad)
            var ah = Math.max(4, height - 2 * pad)
            var U = Math.min(aw / (1 + cV), ah / (1 + 2 * cV))
            var V = U * cV
            var pH = U + V                                // 升维高度（≈ 底面边长）
            var left = pad + (aw - (U + V)) / 2
            var top = pad + (ah - (V + pH)) / 2
            var x0 = left + V                             // 拖拽起点
            var y0 = top + pH
            var ax = x0 + (U + V) / 2                     // 顶点 = 对边中点
            var ay = y0
            var b1x = x0 - V                              // 底边一端（另一条 y 边所在角）
            var b1y = y0 + V
            var b2x = x0 + U                              // 底边另一端（与终点相邻）
            var b2y = y0 + V
            // 实线：与 Python 侧的折线拆分逐段一致（B→C→C'→A'→B'→B 一条 + 顶面前棱 B'C'）
            ctx.beginPath()
            ctx.moveTo(b1x, b1y)                          // B
            ctx.lineTo(b2x, b2y)                          // C（底面前棱）
            ctx.lineTo(b2x, b2y - pH)                     // C'
            ctx.lineTo(ax, ay - pH)                       // A'（顶面顶点）
            ctx.lineTo(b1x, b1y - pH)                     // B'
            ctx.lineTo(b1x, b1y)                          // B（右侧棱）
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(b1x, b1y - pH)
            ctx.lineTo(b2x, b2y - pH)                     // 顶面前棱 B'C'
            ctx.stroke()
            // 虚线（被遮挡棱）：A→B、A→C、A→A'
            // **菜单小图里用点状虚线**（与双曲线小图的渐近线同一套：沿弧长画等距小圆点），
            // 比短划虚线更易读；实际绘制到画布上的虚线样式不变（用户要求）。
            var prDotR = Math.max(0.8, lw / 2)
            var prSpace = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[ax, ay], [b1x, b1y]], prDotR, prSpace)
            dottedPolyline(ctx, [[ax, ay], [b2x, b2y]], prDotR, prSpace)
            dottedPolyline(ctx, [[ax, ay], [ax, ay - pH]], prDotR, prSpace)
            return
        }
        if (root.kind === "tripyramid") {
            // 三棱锥小图：与 Python 侧 `_solid_base_pts` + `_solid_strokes` 同一套结果 ——
            // 底面 = 与三棱柱**完全相同**的等腰三角形投影；顶点 = 底面三角形的**纸面重心**
            // 上移 H（= `_solid_engine_pyramid` 的顶点：底面中心 + (0,0,H)，投影是仿射的
            // → 纸面顶点 = 三个底面点的纸面平均）。
            // 被遮挡棱（点状虚线）由真实管线的"面可见性"算出：**背面那个顶点 A 的三条棱**
            // （A→B、A→C、A→顶点）—— 与三棱柱小图的虚线集合同一个位置关系。
            var kkP = 0.5 * Math.cos(Math.PI / 4)
            var aspP = 2 / Math.sqrt(3)
            var cVP = kkP / (aspP - kkP)
            var awP = Math.max(4, width - 2 * pad)
            var ahP = Math.max(4, height - 2 * pad)
            var UP = Math.min(awP / (1 + cVP), ahP / (1 + 2 * cVP))
            var VP = UP * cVP
            var pHP = UP + VP
            var leftP = pad + (awP - (UP + VP)) / 2
            var topP = pad + (ahP - (VP + pHP)) / 2
            var x0P = leftP + VP
            var y0P = topP + pHP
            var axP = x0P + (UP + VP) / 2                // A（背面顶点）
            var ayP = y0P
            var b1xP = x0P - VP                          // B（底面左角）
            var b1yP = y0P + VP
            var b2xP = x0P + UP                          // C（底面右角）
            var b2yP = y0P + VP
            var oXP = (axP + b1xP + b2xP) / 3            // 顶点 O（底面重心上方 H）
            var oYP = (ayP + b1yP + b2yP) / 3 - pHP
            // 实线：B→C→O→B（底面前棱 + 两条可见侧棱）
            ctx.beginPath()
            ctx.moveTo(b1xP, b1yP)
            ctx.lineTo(b2xP, b2yP)
            ctx.lineTo(oXP, oYP)
            ctx.lineTo(b1xP, b1yP)
            ctx.stroke()
            // 被遮挡棱：A→B、A→C、A→O（点状虚线）
            var tpDotR = Math.max(0.8, lw / 2)
            var tpSpace = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[axP, ayP], [b1xP, b1yP]], tpDotR, tpSpace)
            dottedPolyline(ctx, [[axP, ayP], [b2xP, b2yP]], tpDotR, tpSpace)
            dottedPolyline(ctx, [[axP, ayP], [oXP, oYP]], tpDotR, tpSpace)
            return
        }
        if (root.kind === "trifrustum") {
            // 三棱台小图：与 Python 侧同一套结果 —— 底面 = 与三棱柱/三棱锥**完全相同**的
            // 等腰三角形投影（等边三角形底面）；**棱台的高 = 三棱柱/三棱锥的高 = 底面棱长**
            // （用户要求）→ 外层三棱锥的虚顶点抬到底面重心上方 **2·pH**，再按 ρ = 0.5 截
            // → 顶面正好在 pH 高处、**顶面棱长 = 底面棱长的一半**。
            // 实/虚拆分由真实管线的"面可见性"给出：实线 = B→C→T_C→T_A→T_B→B（底面前棱 +
            // 右侧棱 + 顶面两棱 + 左侧棱）与顶面前棱 T_B→T_C 两笔；点状虚线（被遮挡棱）=
            // 背面顶点 A 的三条棱 A→B、A→C、A→T_A（与三棱柱/三棱锥小图同一位置关系）。
            var kkF = 0.5 * Math.cos(Math.PI / 4)
            var aspF = 2 / Math.sqrt(3)
            var cVF = kkF / (aspF - kkF)
            var awF = Math.max(4, width - 2 * pad)
            var ahF = Math.max(4, height - 2 * pad)
            var UF = Math.min(awF / (1 + cVF), ahF / (1 + 2 * cVF))
            var VF = UF * cVF
            var pHF = UF + VF                            // 外层三棱锥的高（= 底面边长）
            var leftF = pad + (awF - (UF + VF)) / 2
            var topF = pad + (ahF - (VF + pHF)) / 2
            var x0F = leftF + VF
            var y0F = topF + pHF
            var axF = x0F + (UF + VF) / 2                // A（背面顶点）
            var ayF = y0F
            var b1xF = x0F - VF                          // B（底面左角）
            var b1yF = y0F + VF
            var b2xF = x0F + UF                          // C（底面右角）
            var b2yF = y0F + VF
            var oXF = (axF + b1xF + b2xF) / 3            // 虚顶点 O（底面重心上方 **2·pH**）
            var oYF = (ayF + b1yF + b2yF) / 3 - 2 * pHF
            var rhoF = 0.5                               // 截切比 = 0.5 → 顶面在 pH 高处
            var taXF = oXF + rhoF * (axF - oXF)          // 顶面 A'（A 的截点）
            var taYF = oYF + rhoF * (ayF - oYF)
            var tbXF = oXF + rhoF * (b1xF - oXF)         // 顶面 B'
            var tbYF = oYF + rhoF * (b1yF - oYF)
            var tcXF = oXF + rhoF * (b2xF - oXF)         // 顶面 C'
            var tcYF = oYF + rhoF * (b2yF - oYF)
            // 实线：B→C→C'→A'→B'→B 一条折线 + 顶面前棱 B'C' 单独一笔（与 Python 侧折线拆分一致）
            ctx.beginPath()
            ctx.moveTo(b1xF, b1yF)                       // B
            ctx.lineTo(b2xF, b2yF)                       // C（底面前棱）
            ctx.lineTo(tcXF, tcYF)                       // C'（右侧棱）
            ctx.lineTo(taXF, taYF)                       // A'（顶面后棱）
            ctx.lineTo(tbXF, tbYF)                       // B'（顶面左棱）
            ctx.lineTo(b1xF, b1yF)                       // B（左侧棱）
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(tbXF, tbYF)
            ctx.lineTo(tcXF, tcYF)                       // 顶面前棱 B'C'
            ctx.stroke()
            // 虚线（被遮挡棱）：A→B、A→C、A→A'（点状虚线，与三棱柱/三棱锥小图同一套）
            var frDotR = Math.max(0.8, lw / 2)
            var frSpace = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[axF, ayF], [b1xF, b1yF]], frDotR, frSpace)
            dottedPolyline(ctx, [[axF, ayF], [b2xF, b2yF]], frDotR, frSpace)
            dottedPolyline(ctx, [[axF, ayF], [taXF, taYF]], frDotR, frSpace)
            return
        }
        if (root.kind === "quadprism") {
            // 四棱柱小图：与 Python 侧 `_solid_base_pts` + `_solid_strokes` 同一套结果。
            // 底面 = 底面平面里**正方形**（V = U·k/(1-k)，asp(rect) = 1）的投影（一个平行四边形）
            // → 纸面四个角：起点（按下点）、(x0+U+V, y0)、终点 (x0+U, y0+V)、(x0-V, y0+V)。
            // 升维高度 H = 0.72 × 底面边长（画成"方体"而不是正方体，四棱柱更明显）；
            // 被遮挡棱 = 远处的三条（后面那条底棱 + 远侧竖棱 + 左侧底棱）—— 点状虚线。
            var kk4 = 0.5 * Math.cos(Math.PI / 4)
            var cV4 = kk4 / (1 - kk4)                    // V / U
            // 升维高度 = 底面边长 → **正六面体（正方体）**（用户要求：四棱柱小图用正六面体）
            var HK4 = 1.0
            var aw4 = Math.max(4, width - 2 * pad)
            var ah4 = Math.max(4, height - 2 * pad)
            var U4 = Math.min(aw4 / (1 + 2 * cV4), ah4 / (cV4 + HK4 * (1 + cV4)))
            var V4 = U4 * cV4
            var pH4 = HK4 * (U4 + V4)
            var left4 = pad + (aw4 - (U4 + 2 * V4)) / 2
            var top4 = pad + (ah4 - (V4 + pH4)) / 2
            var x04 = left4 + V4
            var y04 = top4 + pH4
            var p0x = x04, p0y = y04                     // 起点（按下点，远离观察者）
            var p1x = x04 + U4 + V4, p1y = y04           // 对边 y 的一端
            var p2x = x04 + U4, p2y = y04 + V4           // 终点所在 y 边的另一端
            var p3x = x04 - V4, p3y = y04 + V4
            // 实线（与 Python 侧的折线拆分逐段一致）：两条折线 + 一条顶面短边
            ctx.beginPath()
            ctx.moveTo(p1x, p1y)
            ctx.lineTo(p2x, p2y)
            ctx.lineTo(p3x, p3y)
            ctx.lineTo(p3x, p3y - pH4)
            ctx.lineTo(p0x, p0y - pH4)
            ctx.lineTo(p1x, p1y - pH4)
            ctx.lineTo(p1x, p1y)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(p2x, p2y)
            ctx.lineTo(p2x, p2y - pH4)
            ctx.lineTo(p1x, p1y - pH4)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(p2x, p2y - pH4)
            ctx.lineTo(p3x, p3y - pH4)
            ctx.stroke()
            // 被遮挡棱：点状虚线（同三棱柱小图）
            var p4DotR = Math.max(0.8, lw / 2)
            var p4Space = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[p0x, p0y], [p1x, p1y]], p4DotR, p4Space)
            dottedPolyline(ctx, [[p0x, p0y], [p3x, p3y]], p4DotR, p4Space)
            dottedPolyline(ctx, [[p0x, p0y], [p0x, p0y - pH4]], p4DotR, p4Space)
            return
        }
        if (root.kind === "quadpyramid") {
            // 四棱锥小图：底面 = 与四棱柱**完全相同**的正方形投影（四个角 p0/p1/p2/p3）；
            // 顶点 = 四个底面点的**纸面平均**上移 H（底面中心 + (0,0,H) 的投影）。
            // 被遮挡棱 = 背面那个角 p0 的三条棱（p0→p1、p0→p3、p0→顶点）—— 与四棱柱小图
            // 的虚线集合同一个位置关系（原 p0→p0' 的竖棱换成 p0→顶点）。
            var kkQ = 0.5 * Math.cos(Math.PI / 4)
            var cVQ = kkQ / (1 - kkQ)
            // 顶点高度 = 底面边长（与四棱柱小图**同一底面、同一高度**：用户要求棱锥与对应的棱柱
            // 底面形状/大小一致、高也相同）
            var HKQ = 1.0
            var awQ = Math.max(4, width - 2 * pad)
            var ahQ = Math.max(4, height - 2 * pad)
            var UQ = Math.min(awQ / (1 + 2 * cVQ), ahQ / (cVQ + HKQ * (1 + cVQ)))
            var VQ = UQ * cVQ
            var pHQ = HKQ * (UQ + VQ)
            var leftQ = pad + (awQ - (UQ + 2 * VQ)) / 2
            var topQ = pad + (ahQ - (VQ + pHQ)) / 2
            var x0Q = leftQ + VQ
            var y0Q = topQ + pHQ
            var q0x = x0Q, q0y = y0Q
            var q1x = x0Q + UQ + VQ, q1y = y0Q
            var q2x = x0Q + UQ, q2y = y0Q + VQ
            var q3x = x0Q - VQ, q3y = y0Q + VQ
            var oXQ = (q0x + q1x + q2x + q3x) / 4        // 顶点（底面重心上方 H）
            var oYQ = (q0y + q1y + q2y + q3y) / 4 - pHQ
            // 实线：p1→p2→p3→O→p1（两条底边 + 三条可见侧棱里的两条）+ p2→O
            ctx.beginPath()
            ctx.moveTo(q1x, q1y)
            ctx.lineTo(q2x, q2y)
            ctx.lineTo(q3x, q3y)
            ctx.lineTo(oXQ, oYQ)
            ctx.lineTo(q1x, q1y)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(q2x, q2y)
            ctx.lineTo(oXQ, oYQ)
            ctx.stroke()
            // 被遮挡棱：p0→p1、p0→p3、p0→O（点状虚线）
            var qpDotR = Math.max(0.8, lw / 2)
            var qpSpace = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[q0x, q0y], [q1x, q1y]], qpDotR, qpSpace)
            dottedPolyline(ctx, [[q0x, q0y], [q3x, q3y]], qpDotR, qpSpace)
            dottedPolyline(ctx, [[q0x, q0y], [oXQ, oYQ]], qpDotR, qpSpace)
            return
        }
        if (root.kind === "cylinder") {
            // 圆柱小图：与 Python 侧 `_solid_cyl_ring` + `_solid_cyl_strokes` 同一套结果 ——
            // 底面 = 底面平面里圆的**投影（椭圆）**；顶面同形上移 H；
            // 只画**两条轮廓竖母线**（椭圆上切线竖直处，tan t = u_y / u_x）；
            // 底面圆环分成前段（实线，含"离观察者最近的采样点"那半圈）与后段（点状虚线）。
            // **测画方式**（`projMode`）只换投影系数：
            //   · 正等测（iso）：三轴轴向变形系数均为 1、水平两轴与水平线夹角 θ = arcsin(1/3)
            //     → u = (2√2/3)(x − y)、v = −(x+y)/3 − z；底面圆投影的椭圆半轴 = √2cosθ·R 与
            //     √2sinθ·R = 4R/3 与 √2R/3 → **长短轴之比恰为 4:√2**（用户指定）。
            //   · 斜二测（oblique）：u = y + k·x、v = −(z + k·x)（k = 0.5cos45°）
            var isoM = root.projMode !== "oblique"
            var kkC = 0.5 * Math.cos(Math.PI / 4)
            var isoC = 2.0 * Math.sqrt(2.0) / 3.0     // cosθ
            var isoS = 1.0 / 3.0                      // sinθ
            var UXC = isoM ? isoC : kkC          // u 对平面 x 的系数
            var UYC = isoM ? -isoC : 1.0         // u 对平面 y 的系数
            var VXC = isoM ? -isoS : -kkC        // v 对平面 x 的系数
            var VYC = isoM ? -isoS : 0.0         // v 对平面 y 的系数
            var AWX = Math.hypot(UXC, UYC)      // 单位圆的 u 半宽
            var AWY = Math.hypot(VXC, VYC)      // 单位圆的 v 半高
            var awC = Math.max(4, width - 2 * pad)
            var ahC = Math.max(4, height - 2 * pad)
            // 升维高度 = **底面圆直径**（2R，用户要求：圆柱小图的高 = 底面圆直径）
            var HKC = 2.0
            var rC = Math.min(awC / (2 * AWX), ahC / (2 * AWY + HKC))
            var HC = HKC * rC
            var cW = 2 * AWX * rC
            var cH = 2 * AWY * rC
            var cxC = pad + (awC - cW) / 2 + cW / 2
            var cyC = pad + (ahC - (cH + HC)) / 2 + cH / 2 + HC
            var NC = 128
            var ringC = []
            for (var iC = 0; iC <= NC; iC++) {
                var tC = 2 * Math.PI * iC / NC
                var xpC = rC * Math.cos(tC)
                var ypC = rC * Math.sin(tC)
                ringC.push([cxC + UXC * xpC + UYC * ypC, cyC + VXC * xpC + VYC * ypC])
            }
            var stepC = 2 * Math.PI / NC
            // ⚠️ 必须把模运算结果夹回 [0, NC)：JS 的 % 会保留负号（正等测时 atan2(−s3, s3) = −45°
            // → 负数下标）→ 下标为负会让下面的 cylArc 永远追不到终点（死循环卡住整个界面）。
            var i0C = ((Math.round(Math.atan2(UYC, UXC) / stepC) % NC) + NC) % NC
            var i1C = (i0C + Math.floor(NC / 2)) % NC          // 对径的另一条轮廓母线
            var cylArc = function (i0, i1) {
                var pts = [ringC[i0]]
                var i = i0
                for (var n = 0; n < NC; n++) {                 // 带上限：万一终点不可达也不会死循环
                    if (i === i1) break
                    i = (i + 1) % NC
                    pts.push(ringC[i])
                }
                return pts
            }
            // 前段（可见）= 包含"离观察者最近的采样点"的那半圈（与 Python 侧同判据）
            var arcA = cylArc(i0C, i1C)
            var arcB = cylArc(i1C, i0C)
            var tNear = (isoM ? Math.atan2(-1, -1) : Math.atan2(kkC, -1)) % (2 * Math.PI)
            if (tNear < 0) tNear += 2 * Math.PI
            var iNear = ((Math.round(tNear / stepC) % NC) + NC) % NC
            var inArc = function (arc) {
                for (var q = 0; q < arc.length; q++) if (arc[q] === ringC[iNear]) return true
                return false
            }
            var frontC = inArc(arcA) ? arcA : arcB
            var rearC = inArc(arcA) ? arcB : arcA
            // 顶面整圈（实线）
            ctx.beginPath()
            ctx.moveTo(ringC[0][0], ringC[0][1] - HC)
            for (var jC = 1; jC <= NC; jC++) {
                ctx.lineTo(ringC[jC][0], ringC[jC][1] - HC)
            }
            ctx.stroke()
            // 底面：前段实线
            ctx.beginPath()
            ctx.moveTo(frontC[0][0], frontC[0][1])
            for (var fC = 1; fC < frontC.length; fC++) {
                ctx.lineTo(frontC[fC][0], frontC[fC][1])
            }
            ctx.stroke()
            // 两条轮廓竖母线（实线）
            ctx.beginPath()
            ctx.moveTo(ringC[i0C][0], ringC[i0C][1])
            ctx.lineTo(ringC[i0C][0], ringC[i0C][1] - HC)
            ctx.moveTo(ringC[i1C][0], ringC[i1C][1])
            ctx.lineTo(ringC[i1C][0], ringC[i1C][1] - HC)
            ctx.stroke()
            // 底面后段：点状虚线（同其它立体小图）
            var cDotR = Math.max(0.8, lw / 2)
            var cSpace = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, rearC, cDotR, cSpace)
            return
        }
        if (root.kind === "cone") {
            // 圆锥小图：与 Python 侧 `_solid_cyl_ring` + `_solid_cone_strokes` 同一套结果 ——
            // 底面 = 底面平面里圆的**投影（椭圆）**（尺寸/位置与圆柱小图完全一致）；
            // 顶点 = 底面中心上方 H（H = 1.5R）；**两条轮廓母线 = 顶点到底面椭圆的两个切点**。
            // 切点用解析解：把顶点搬回底面平面（p = M⁻¹·off，off = (0, −H) 的投影）→
            // θ = atan2(p_y, p_x)、α = arccos(R/|p|) → 两个切点角度 = θ ∓ α（与 Python 逐位一致）。
            // 底面圆环**背离顶点**的那段实线、朝向顶点的那段点状虚线。
            var isoN = root.projMode !== "oblique"
            var kkN = 0.5 * Math.cos(Math.PI / 4)
            var isoCN = 2.0 * Math.sqrt(2.0) / 3.0
            var isoSN = 1.0 / 3.0
            var UXN = isoN ? isoCN : kkN
            var UYN = isoN ? -isoCN : 1.0
            var VXN = isoN ? -isoSN : -kkN
            var VYN = isoN ? -isoSN : 0.0
            var AWN = Math.hypot(UXN, UYN)
            var AHN = Math.hypot(VXN, VYN)
            var awN = Math.max(4, width - 2 * pad)
            var ahN = Math.max(4, height - 2 * pad)
            // 顶点高度 = **底面圆直径**（2R，与圆柱小图**同一底面、同一高度**：用户要求）
            var HKN = 2.0
            var rN = Math.min(awN / (2 * AWN), ahN / (2 * AHN + HKN))
            var HN = HKN * rN
            var wN = 2 * AWN * rN
            var hN = 2 * AHN * rN
            var cxN = pad + (awN - wN) / 2 + wN / 2
            var cyN = pad + (ahN - (hN + HN)) / 2 + hN / 2 + HN
            var NN = 128
            var ringN = []
            for (var iN = 0; iN <= NN; iN++) {
                var tN = 2 * Math.PI * iN / NN
                ringN.push([cxN + (UXN * Math.cos(tN) + UYN * Math.sin(tN)) * rN,
                            cyN + (VXN * Math.cos(tN) + VYN * Math.sin(tN)) * rN])
            }
            var apexN = [cxN, cyN - HN]
            var offXN = 0.0
            var offYN = -HN          // (0, dz) 的投影：两种测画法下 u_z = 0、v_z = -1
            var detN = UXN * VYN - UYN * VXN
            var pxN = (VYN * offXN - UYN * offYN) / detN      // p = M⁻¹·off
            var pyN = (UXN * offYN - VXN * offXN) / detN
            var dN = Math.hypot(pxN, pyN)
            var stepN = 2 * Math.PI / NN
            if (dN <= rN * (1 + 1e-9)) {
                // 切线不存在（圆锥压得很扁、顶点落在底面椭圆内部）→ 整个轮廓就是底面椭圆
                ctx.beginPath()
                ctx.moveTo(ringN[0][0], ringN[0][1])
                for (var iN2 = 1; iN2 <= NN; iN2++) ctx.lineTo(ringN[iN2][0], ringN[iN2][1])
                ctx.stroke()
                return
            }
            var alphN = Math.acos(Math.max(-1, Math.min(1, rN / dN)))
            var thN = Math.atan2(pyN, pxN)
            // ⚠️ 模运算结果必须夹回 [0, NN)：JS 的 % 会保留负号（同圆柱小图那个死循环坑）
            var i0N = ((Math.round((thN - alphN) / stepN) % NN) + NN) % NN
            var i1N = ((Math.round((thN + alphN) / stepN) % NN) + NN) % NN
            var coneArc = function (a0, a1) {
                var pts = [ringN[a0]]
                var q = a0
                for (var n2 = 0; n2 < NN; n2++) {          // 带上限：终点不可达也不死循环
                    if (q === a1) break
                    q = (q + 1) % NN
                    pts.push(ringN[q])
                }
                return pts
            }
            var arcAN = coneArc(i0N, i1N)
            var arcBN = coneArc(i1N, i0N)
            // 可见弧 = 背离顶点的那段（两段中点沿 −off 方向更远的那个，与 Python 同判据）
            var midAN = arcAN[Math.floor(arcAN.length / 2)]
            var midBN = arcBN[Math.floor(arcBN.length / 2)]
            var dotAN = -((midAN[0] - cxN) * offXN + (midAN[1] - cyN) * offYN)
            var dotBN = -((midBN[0] - cxN) * offXN + (midBN[1] - cyN) * offYN)
            var frontN = dotAN > dotBN ? arcAN : arcBN
            var rearN = dotAN > dotBN ? arcBN : arcAN
            // 前段实线
            ctx.beginPath()
            ctx.moveTo(frontN[0][0], frontN[0][1])
            for (var fN = 1; fN < frontN.length; fN++) {
                ctx.lineTo(frontN[fN][0], frontN[fN][1])
            }
            ctx.stroke()
            // 两条轮廓母线（顶点 → 切点，实线）
            ctx.beginPath()
            ctx.moveTo(apexN[0], apexN[1])
            ctx.lineTo(ringN[i0N][0], ringN[i0N][1])
            ctx.moveTo(apexN[0], apexN[1])
            ctx.lineTo(ringN[i1N][0], ringN[i1N][1])
            ctx.stroke()
            // 后段：点状虚线（同其它立体小图）
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, rearN, Math.max(0.8, lw / 2), Math.max(3.0, lw * 2.2))
            return
        }
        if (root.kind === "quadfrustum") {
            // 四棱台小图：与 Python 侧 `_solid_base_pts` + `_solid_frustum_strokes` 同一套结果 ——
            // 底面 = 与四棱柱/四棱锥**完全相同**的正方形投影（同一个 U/V/cV 与 pH = 边长）；
            // **棱台的高 = 四棱柱/四棱锥的高 = 底面棱长**（用户要求）→ 外层四棱锥的虚顶点
            // 抬到 **2·pH**，再按 ρ = 0.5 截 → 顶面在 pH 高处、顶面棱长 = 底面棱长的一半。
            // 实/虚拆分由真实管线的"面可见性"给出：实线 = p1→p2→p3→T3→T0→T1→p1（底面前两条棱 +
            // 左侧棱 + 顶面后两条棱 + 右侧棱）与 p2→T2→T1 两笔 + 顶面前棱 T2→T3 一笔；
            // 点状虚线（被遮挡棱）= **远处角点 p0 的三条棱** p0→p1、p0→p3、p0→T0。
            var kkQ = 0.5 * Math.cos(Math.PI / 4)
            var cVQ = kkQ / (1 - kkQ)                    // 正方形底面：V = U·cV
            var HKQ = 1.0                                // 升维高度 = 底面边长（与四棱锥同）
            var awQ = Math.max(4, width - 2 * pad)
            var ahQ = Math.max(4, height - 2 * pad)
            var UQ = Math.min(awQ / (1 + 2 * cVQ), ahQ / (cVQ + HKQ * (1 + cVQ)))
            var VQ = UQ * cVQ
            var pHQ = HKQ * (UQ + VQ)
            var leftQ = pad + (awQ - (UQ + 2 * VQ)) / 2
            var topQ = pad + (ahQ - (VQ + pHQ)) / 2
            var x0Q = leftQ + VQ
            var y0Q = topQ + pHQ
            var p0x = x0Q, p0y = y0Q                      // p0（远角点 = 按下点）
            var p1x = x0Q + UQ + VQ, p1y = y0Q
            var p2x = x0Q + UQ, p2y = y0Q + VQ
            var p3x = x0Q - VQ, p3y = y0Q + VQ
            var apXQ = x0Q + UQ / 2                       // 虚顶点（底面中心上方 **2·pH**）
            var apYQ = y0Q + VQ / 2 - 2 * pHQ
            var rhoQ = 0.5                                // 截切比 = 0.5 → 顶面在 pH 高处
            var t0x = apXQ + rhoQ * (p0x - apXQ), t0y = apYQ + rhoQ * (p0y - apYQ)
            var t1x = apXQ + rhoQ * (p1x - apXQ), t1y = apYQ + rhoQ * (p1y - apYQ)
            var t2x = apXQ + rhoQ * (p2x - apXQ), t2y = apYQ + rhoQ * (p2y - apYQ)
            var t3x = apXQ + rhoQ * (p3x - apXQ), t3y = apYQ + rhoQ * (p3y - apYQ)
            // 实线（与 Python 侧的折线拆分逐段一致）
            ctx.beginPath()
            ctx.moveTo(p1x, p1y)
            ctx.lineTo(p2x, p2y)
            ctx.lineTo(p3x, p3y)
            ctx.lineTo(t3x, t3y)
            ctx.lineTo(t0x, t0y)
            ctx.lineTo(t1x, t1y)
            ctx.lineTo(p1x, p1y)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(p2x, p2y)
            ctx.lineTo(t2x, t2y)
            ctx.lineTo(t1x, t1y)
            ctx.stroke()
            ctx.beginPath()
            ctx.moveTo(t2x, t2y)
            ctx.lineTo(t3x, t3y)                          // 顶面前棱 T2→T3
            ctx.stroke()
            // 虚线（被遮挡棱）：p0→p1、p0→p3、p0→T0（点状虚线，与其它立体小图同一套）
            var qfDotR = Math.max(0.8, lw / 2)
            var qfSpace = Math.max(3.0, lw * 2.2)
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, [[p0x, p0y], [p1x, p1y]], qfDotR, qfSpace)
            dottedPolyline(ctx, [[p0x, p0y], [p3x, p3y]], qfDotR, qfSpace)
            dottedPolyline(ctx, [[p0x, p0y], [t0x, t0y]], qfDotR, qfSpace)
            return
        }
        if (root.kind === "conefrustum") {
            // 圆台小图：与 Python 侧 `_solid_cyl_ring` + `_solid_cfrustum_strokes` 同一套结果 ——
            // 底面 = 底面平面里圆的投影（椭圆，尺寸/位置/测画方式与圆柱/圆锥小图完全一致）；
            // **棱台的高 = 圆柱/圆锥的高 = 底面圆直径 2R**（用户要求）→ 外层圆锥的虚顶点
            // 抬到 **2·H**（= 4R），再按 ρ = 0.5 截 → 顶面圆在 H 高处、半径 = 0.5R；
            // 顶面椭圆**整圈实线**；底面圆环**背离顶点**的那段实线、朝向顶点的那段点状虚线；
            // 两条轮廓母线 = 那个虚顶点圆锥的两条轮廓母线（切点解析解与圆锥同一套，但用**抬高的
            // 虚顶点**），只画"底面环 → 顶面环"这一段。
            var isoF = root.projMode !== "oblique"
            var kkF2 = 0.5 * Math.cos(Math.PI / 4)
            var isoCF = 2.0 * Math.sqrt(2.0) / 3.0
            var isoSF = 1.0 / 3.0
            var UXF = isoF ? isoCF : kkF2
            var UYF = isoF ? -isoCF : 1.0
            var VXF = isoF ? -isoSF : -kkF2
            var VYF = isoF ? -isoSF : 0.0
            var AWF = Math.hypot(UXF, UYF)
            var ADF = Math.hypot(VXF, VYF)
            var awF2 = Math.max(4, width - 2 * pad)
            var ahF2 = Math.max(4, height - 2 * pad)
            var HKF = 2.0
            var rF = Math.min(awF2 / (2 * AWF), ahF2 / (2 * ADF + HKF))
            var HF = HKF * rF
            var wF = 2 * AWF * rF
            var hF = 2 * ADF * rF
            var cxF = pad + (awF2 - wF) / 2 + wF / 2
            var cyF = pad + (ahF2 - (hF + HF)) / 2 + hF / 2 + HF
            var NF = 128
            var ringF = []
            for (var iF = 0; iF <= NF; iF++) {
                var tF = 2 * Math.PI * iF / NF
                ringF.push([cxF + (UXF * Math.cos(tF) + UYF * Math.sin(tF)) * rF,
                            cyF + (VXF * Math.cos(tF) + VYF * Math.sin(tF)) * rF])
            }
            var apXF = cxF
            var apYF = cyF - 2 * HF
            var rhoCF = 0.5
            // 顶面圆环：每点 = 顶点 + ρ·(底面点 − 顶点)（投影是仿射的 → 纸面上同样插值）
            var cutF = []
            for (var iF2 = 0; iF2 <= NF; iF2++) {
                cutF.push([apXF + rhoCF * (ringF[iF2][0] - apXF),
                           apYF + rhoCF * (ringF[iF2][1] - apYF)])
            }
            var offXF = 0.0
            var offYF = -2 * HF      // 虚顶点 (0, 2H) 的投影：两种测画法下 u_z = 0、v_z = -1
            var detF = UXF * VYF - UYF * VXF
            var pxF = (VYF * offXF - UYF * offYF) / detF      // p = M⁻¹·off
            var pyF = (UXF * offYF - VXF * offXF) / detF
            var stepF = 2 * Math.PI / NF
            if (Math.hypot(pxF, pyF) <= rF * (1 + 1e-9)) {
                // 切线不存在（虚顶点落在底面椭圆内部）→ 底面椭圆整圈实线 + 顶面圈虚线
                ctx.beginPath()
                ctx.moveTo(ringF[0][0], ringF[0][1])
                for (var iF3 = 1; iF3 <= NF; iF3++) ctx.lineTo(ringF[iF3][0], ringF[iF3][1])
                ctx.stroke()
                ctx.fillStyle = root.lineColor
                dottedPolyline(ctx, cutF, Math.max(0.8, lw / 2), Math.max(3.0, lw * 2.2))
                return
            }
            var alphF = Math.acos(Math.max(-1, Math.min(1, rF / Math.hypot(pxF, pyF))))
            var thF = Math.atan2(pyF, pxF)
            // ⚠️ 模运算结果必须夹回 [0, NF)：JS 的 % 会保留负号（同圆柱/圆锥那个坑）
            var i0F = ((Math.round((thF - alphF) / stepF) % NF) + NF) % NF
            var i1F = ((Math.round((thF + alphF) / stepF) % NF) + NF) % NF
            var cfArc = function (a0, a1) {
                var pts = [ringF[a0]]
                var q = a0
                for (var n3 = 0; n3 < NF; n3++) {          // 带上限：终点不可达也不死循环
                    if (q === a1) break
                    q = (q + 1) % NF
                    pts.push(ringF[q])
                }
                return pts
            }
            var arcAF = cfArc(i0F, i1F)
            var arcBF = cfArc(i1F, i0F)
            // 可见弧 = 背离虚顶点的那段（两段中点沿 −off 方向更远的那个，与 Python 同判据）
            var midAF = arcAF[Math.floor(arcAF.length / 2)]
            var midBF = arcBF[Math.floor(arcBF.length / 2)]
            var dotAF = -((midAF[0] - cxF) * offXF + (midAF[1] - cyF) * offYF)
            var dotBF = -((midBF[0] - cxF) * offXF + (midBF[1] - cyF) * offYF)
            var frontF = dotAF > dotBF ? arcAF : arcBF
            var rearF = dotAF > dotBF ? arcBF : arcAF
            // 顶面整圈（实线）
            ctx.beginPath()
            ctx.moveTo(cutF[0][0], cutF[0][1])
            for (var jF = 1; jF <= NF; jF++) ctx.lineTo(cutF[jF][0], cutF[jF][1])
            ctx.stroke()
            // 底面：背离顶点的那段实线
            ctx.beginPath()
            ctx.moveTo(frontF[0][0], frontF[0][1])
            for (var fF = 1; fF < frontF.length; fF++) ctx.lineTo(frontF[fF][0], frontF[fF][1])
            ctx.stroke()
            // 两条轮廓母线（底面环切点 → 顶面环对应点，实线）
            ctx.beginPath()
            ctx.moveTo(ringF[i0F][0], ringF[i0F][1])
            ctx.lineTo(cutF[i0F][0], cutF[i0F][1])
            ctx.moveTo(ringF[i1F][0], ringF[i1F][1])
            ctx.lineTo(cutF[i1F][0], cutF[i1F][1])
            ctx.stroke()
            // 底面朝向顶点的那段：点状虚线（同其它立体小图）
            ctx.fillStyle = root.lineColor
            dottedPolyline(ctx, rearF, Math.max(0.8, lw / 2), Math.max(3.0, lw * 2.2))
            return
        }
        if (root.kind === "sphere") {
            // 球小图：与 Python 侧 `_solid_sphere_strokes` 同一套结果 ——
            // 轮廓圆（= 球的投影）+ 两个"半径圆"的投影椭圆（正等测：长半轴 : 短半轴 = 1 : √2/4）：
            //   ① 与 xOy 平行的过球心大圆 → 长轴水平：**下半实线 / 上半点状虚线**；
            //   ② 长轴竖直的那个 → **左半实线 / 右半点状虚线**。
            // ⚠️ 球固定用**正等测**（后端 `solidProjMode` 可能还停在上一次给圆柱/圆锥选的
            //    斜二测上）→ 这个分支**固定按正等测**算，与后端 `_solid_proj_for("sphere")` 一致。
            var isoCSp = 2.0 * Math.sqrt(2.0) / 3.0
            var isoSSp = 1.0 / 3.0
            var awSp = Math.hypot(isoCSp, -isoCSp)     // 单位水平大圆投影椭圆的半宽 = 4/3
            var ahSp = Math.hypot(-isoSSp, -isoSSp)    // ……的半高 = √2/3
            var kkS = ahSp / awSp                      // 短半轴 / 长半轴 = √2/4
            var bwSp = Math.max(4, width - 2 * pad)
            var bhSp = Math.max(4, height - 2 * pad)
            var rSp = Math.min(bwSp, bhSp) / 2
            var cxSp = pad + bwSp / 2
            var cySp = pad + bhSp / 2
            var NSp = 128
            // 轮廓圆（实线、闭合）
            ctx.beginPath()
            for (var iSp = 0; iSp <= NSp; iSp++) {
                var tSp = 2 * Math.PI * iSp / NSp
                var qxSp = cxSp + rSp * Math.cos(tSp)
                var qySp = cySp + rSp * Math.sin(tSp)
                if (iSp === 0) ctx.moveTo(qxSp, qySp)
                else ctx.lineTo(qxSp, qySp)
            }
            ctx.stroke()
            // ① 赤道椭圆下半（实线：t 从 0（右）→ π（左），中间过最低点）
            var spHalf = function (ax, ay, t0, t1) {
                var pts = []
                for (var i2 = 0; i2 <= NSp / 2; i2++) {
                    var t2 = t0 + (t1 - t0) * i2 / (NSp / 2)
                    pts.push([cxSp + ax * Math.cos(t2), cySp + ay * Math.sin(t2)])
                }
                return pts
            }
            var eqDown = spHalf(rSp, rSp * kkS, 0, Math.PI)
            var eqUp = spHalf(rSp, rSp * kkS, Math.PI, 2 * Math.PI)
            var vLeft = spHalf(rSp * kkS, rSp, Math.PI / 2, 1.5 * Math.PI)
            var vRight = spHalf(rSp * kkS, rSp, -Math.PI / 2, Math.PI / 2)
            ctx.beginPath()
            ctx.moveTo(eqDown[0][0], eqDown[0][1])
            for (var fE = 1; fE < eqDown.length; fE++) ctx.lineTo(eqDown[fE][0], eqDown[fE][1])
            ctx.moveTo(vLeft[0][0], vLeft[0][1])
            for (var fV = 1; fV < vLeft.length; fV++) ctx.lineTo(vLeft[fV][0], vLeft[fV][1])
            ctx.stroke()
            // ② 两段被遮挡的半圈：点状虚线（同其它立体小图）
            ctx.fillStyle = root.lineColor
            var spDotR = Math.max(0.8, lw / 2)
            var spSpace = Math.max(3.0, lw * 2.2)
            dottedPolyline(ctx, eqUp, spDotR, spSpace)
            dottedPolyline(ctx, vRight, spDotR, spSpace)
            return
        }
        if (root.kind === "planeaxes" || root.kind === "spaceaxes") {
            // 坐标系小图（形状菜单"坐标系"页，每行两列）：**几条相交的带箭头直线** ——
            // 箭头画法与直线菜单的"箭头"完全一致（臂长 max(6, 2.5w)、半角 30°、尖端在端点，
            // 见 Python `_draw_arrow_head` / LineStylePreview）。
            //   · planeaxes  平面直角坐标系：原点在框中心，横轴左右各半（箭头朝右）、
            //                纵轴上下各半（箭头朝上）；
            //   · spaceaxes  空间直角坐标系：斜二测的左手系分布 —— x 轴朝右上 45°、
            //                y 轴水平朝右、z 轴竖直朝上（三轴等长）。
            var _lwA = Math.max(1, root.lineWidth)
            var _hlA = Math.max(6, _lwA * 2.5)
            var _blA = _hlA * Math.cos(Math.PI / 6)
            var _slA = _hlA * Math.sin(Math.PI / 6)
            var _arrowAt = function (tx, ty, ux, uy) {
                // 尖端 (tx,ty)、方向 (ux,uy)（单位向量）：两条臂从尖端向后展开 bl、
                // 法向 ±sl（半角 30°）—— 与 Python `_draw_arrow_head` 逐字一致
                // （⚠️ 法向必须是 n = (−uy, ux)；曾经写成 (uy, ux) 在斜轴（x 轴 45°）上
                //     两条臂会同时**落在轴上** → 看上去"没有箭头"，用户报的问题）
                var _nx = -uy
                var _ny = ux
                ctx.beginPath()
                ctx.moveTo(tx - ux * _blA + _nx * _slA, ty - uy * _blA + _ny * _slA)
                ctx.lineTo(tx, ty)
                ctx.lineTo(tx - ux * _blA - _nx * _slA, ty - uy * _blA - _ny * _slA)
                ctx.stroke()
            }
            var _axis = function (x0, y0, x1, y1) {
                ctx.beginPath()
                ctx.moveTo(x0, y0)
                ctx.lineTo(x1, y1)
                ctx.stroke()
                var _dx = x1 - x0, _dy = y1 - y0
                var _ln = Math.hypot(_dx, _dy)
                if (_ln > 1e-6) _arrowAt(x1, y1, _dx / _ln, _dy / _ln)
            }
            ctx.lineWidth = _lwA
            ctx.lineCap = "round"
            ctx.lineJoin = "round"
            if (root.kind === "planeaxes") {
                var _cxA = width / 2
                var _cyA = height / 2
                var _hxA = (width - 2 * pad) / 2
                var _hyA = (height - 2 * pad) / 2
                _axis(_cxA - _hxA, _cyA, _cxA + _hxA, _cyA)     // 横轴（指向右）
                _axis(_cxA, _cyA + _hyA, _cxA, _cyA - _hyA)     // 纵轴（指向上）
            } else {
                // 三条轴从原点出发（用户给的截图方向）：z 轴**竖直向上**、y 轴**水平向右**，
                // 两者等长 L；x 轴指向**左下 45°**、屏幕上投影后的长度 = **L/2**
                // （→ 它的水平/竖直分量各 = L·√2/4）。
                // 三轴的整体外框是正方形（边长 = L + L·√2/4 = L·(1+√2/4)）→ 在格子里居中。
                var _wA = width - 2 * pad
                var _hA = height - 2 * pad
                var _kA = 1 + Math.SQRT2 / 4
                var _LA = Math.min(_wA, _hA) / _kA
                var _sA = _LA * Math.SQRT1_2 / 2
                var _oxA = pad + _sA
                var _oyA = pad + _hA - _sA
                _axis(_oxA, _oyA, _oxA - _sA, _oyA + _sA)   // x 轴（左下，投影长 = L/2）
                _axis(_oxA, _oyA, _oxA + _LA, _oyA)          // y 轴（右，长 L）
                _axis(_oxA, _oyA, _oxA, _oyA - _LA)          // z 轴（上，长 L）
            }
            return
        }
        var loop = loopPoints(root.kind, pad, pad, width - pad, height - pad)
        ctx.beginPath()
        ctx.moveTo(loop[0][0], loop[0][1])
        for (var i = 1; i < loop.length; i++) ctx.lineTo(loop[i][0], loop[i][1])
        ctx.stroke()
    }
}
