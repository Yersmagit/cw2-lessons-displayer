import QtQuick 2.15

// 等边吸附提示：胶囊形（虚线边框）+ 左侧一个小等边图形 + 名称，显示在鼠标上方。
// 形状与虚线边框都用 Canvas 自绘：QML 的 Rectangle 边框画不了虚线，故按"圆角矩形
// 周长参数化"逐段画 dash —— 直线段与四角圆弧上都能得到均匀的短划。
Item {
    id: root
    objectName: "snapHint"

    property string shapeKind: ""        // tri / rect / pent / hex
    property string label: ""            // 等边三角形 / 正方形 / 等腰直角三角形 / 30° 直角三角形 ...
    property real shapesAspect: 1.0      // 该图形"等边"时的辅助矩形长宽比（w/h）
    property bool lightMode: true
    // 是否显示左侧小图标（默认显示）；提示"水平排列"/"竖直排列"用纯文字胶囊（showIcon = false）
    property bool showIcon: true
    readonly property color lineColor: "#1E88E5"     // 与选中蓝边一致（SELECTION_BLUE）
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color bg: lightMode ? "#F2FFFFFF" : "#F20A0A0A"
    readonly property int padX: 10
    readonly property int gap: 7
    // 提示里的小图形高：椭圆/双曲线/抛物线稍大一点（胶囊高固定 26，不影响布局）
    readonly property bool isBigIcon: root.shapeKind === "ellipse"
                                      || root.shapeKind === "ellipse2"
                                      || root.shapeKind === "hyp"
                                      || root.shapeKind === "hypas"
                                      || root.shapeKind === "para"
                                      || root.shapeKind === "para2"
    readonly property int iconH: root.isBigIcon ? 20 : 16
    readonly property int radius: height / 2
    readonly property int dashLen: 4
    readonly property int gapLen: 3

    // 宽按内容算；给个最小宽度——离屏/缺字体环境下 CJK 文字可能量不出宽度，
    // 以免胶囊退化成很小一团（真机上文字有正常宽度，下限不会生效）。
    // **不带小图标**时用更小的左右内边距，且**不留图标宽度**（否则文字右侧会空出一片，
    // 整个胶囊显得过宽）。
    readonly property int padXNoIcon: 8
    width: root.showIcon
           ? Math.max(64, padX * 2 + iconW + gap + labelText.implicitWidth)
           : Math.max(18, padXNoIcon * 2 + labelText.implicitWidth)
    height: 26

    // 小图形宽 = 高 × 等边长宽比（保证提示里画出来的就是等边形状）；
    // 但**限制最大宽度**：30° 直角三角的长宽比 ≈ 1.732，按 16 高算出来 28px 宽会把
    // 胶囊撑长 → 触顶时改为按最大宽反算高度（iconHUsed），角度不变、只是整体小一号。
    // 未触顶时高度保持 iconH 不变（否则 iconW 的四舍五入会让图形略变矮）。
    readonly property int maxIconW: 22
    readonly property real iconWfull: Math.max(10, Math.round(root.iconH * root.shapesAspect))
    readonly property real iconW: Math.min(root.maxIconW, root.iconWfull)
    readonly property real iconHUsed: (root.shapesAspect > 1e-6 && root.iconWfull > root.maxIconW)
                                      ? root.iconW / root.shapesAspect : root.iconH

    Rectangle {
        anchors.fill: parent
        radius: root.radius
        color: root.bg
    }

    // 虚线圆角边框（按周长参数化分段，直线与圆弧都均匀）
    Canvas {
        id: borderCanvas
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var w = width, h = height, r = root.radius
            var inset = 0.5
            var l = inset, t = inset, rr = w - inset, bb = h - inset
            var rad = Math.min(r, (bb - t) / 2, (rr - l) / 2)
            // 周长参数 → 点（四个直角 + 四条直线，顺序：上边→右上角→右边→右下角→下边→左下角→左边→左上角）
            var straights = [[l + rad, t, rr - rad, t],
                             [rr, t + rad, rr, bb - rad],
                             [rr - rad, bb, l + rad, bb],
                             [l, bb - rad, l, t + rad]]
            var arcs = [[rr - rad, t + rad, rad, -90, 0],      // 右上
                        [rr - rad, bb - rad, rad, 0, 90],      // 右下
                        [l + rad, bb - rad, rad, 90, 180],     // 左下
                        [l + rad, t + rad, rad, 180, 270]]     // 左上
            var segs = []
            var total = 0
            for (var i = 0; i < 4; i++) {
                var s = straights[i]
                var len = Math.hypot(s[2] - s[0], s[3] - s[1])
                segs.push({kind: "line", x0: s[0], y0: s[1], x1: s[2], y1: s[3], len: len})
                total += len
                var a = arcs[i]
                var alen = Math.PI / 2 * a[2]
                segs.push({kind: "arc", cx: a[0], cy: a[1], r: a[2], a0: a[3], a1: a[4], len: alen})
                total += alen
            }
            ctx.lineWidth = 1
            ctx.lineCap = "butt"
            ctx.strokeStyle = root.lineColor
            var pos = 0
            while (pos < total) {
                var end = Math.min(total, pos + root.dashLen)
                // 把 [pos, end] 映射到路径上的点，逐段（跨段时拆成多段短划）
                var p0 = pointAt(segs, pos)
                var p1 = pointAt(segs, end)
                ctx.beginPath()
                ctx.moveTo(p0[0], p0[1])
                ctx.lineTo(p1[0], p1[1])
                ctx.stroke()
                pos = end + root.gapLen
            }
        }
        function pointAt(segs, s) {
            var acc = 0
            for (var i = 0; i < segs.length; i++) {
                var sg = segs[i]
                if (s <= acc + sg.len || i === segs.length - 1) {
                    var t = Math.max(0, Math.min(1, (s - acc) / Math.max(1e-6, sg.len)))
                    if (sg.kind === "line")
                        return [sg.x0 + (sg.x1 - sg.x0) * t, sg.y0 + (sg.y1 - sg.y0) * t]
                    var ang = (sg.a0 + (sg.a1 - sg.a0) * t) * Math.PI / 180
                    return [sg.cx + sg.r * Math.cos(ang), sg.cy + sg.r * Math.sin(ang)]
                }
                acc += sg.len
            }
            return [0, 0]
        }
    }

    // 左侧小图形（与图形菜单同一套顶点公式；showIcon = false 时不画也不占宽度）
    ShapeIconPreview {
        id: icon
        objectName: "hintIcon"
        visible: root.showIcon
        anchors.left: parent.left
        anchors.leftMargin: root.padX
        anchors.verticalCenter: parent.verticalCenter
        width: root.showIcon ? root.iconW : 0
        height: root.showIcon ? root.iconHUsed : 0
        kind: root.showIcon ? root.shapeKind : ""
        lineWidth: 1.4
        lineColor: root.fg
        // 椭圆：更饱满（0.88），且轮廓用虚线（与胶囊虚线边框同一风格）；
        // 其它图形不受影响（这两项只在椭圆分支里被读）
        ellipsePlump: (root.shapeKind === "ellipse" || root.shapeKind === "ellipse2") ? 0.88 : 0.78
        ellipseDashed: root.shapeKind === "ellipse" || root.shapeKind === "ellipse2"
    }

    Text {
        id: labelText
        objectName: "hintLabel"
        anchors.left: root.showIcon ? icon.right : parent.left
        anchors.leftMargin: root.showIcon ? root.gap : root.padXNoIcon
        anchors.verticalCenter: parent.verticalCenter
        text: root.label
        color: root.fg
        font.family: Qt.application.font.family
        font.pixelSize: 12
    }
}
