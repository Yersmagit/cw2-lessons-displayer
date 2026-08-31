import QtQuick 2.15

// 选择工具覆盖层（仅"交互智能平板" + "选择"工具时启用，层级由 SpecialModeWindow 指定 z60）：
// - 圈选：Canvas 实时绘制 2px 虚线（每段 2px、间隔 2px、圆端头 ≈ 半径1px 的圆）
//   围成闭合多边形，并填充低透明度蓝色；圈选过程中后端实时计算被完全包裹的
//   笔划（所有离散点都在多边形内）并烘进 1px 蓝色描边。
// - 单击：命中某笔划则单选该笔划，未命中则取消选择（或保持选中矩形内空白）。
// - 确认选择后：显示 1px 蓝色边框矩形（无填充）+ 四角白色填充/黑色 1px 边框的圆把手；
//   拖拽四角把手等比缩放选中笔划，拖拽矩形边框条带平移选中笔划（条带避让四角把手）。
Item {
    id: root
    objectName: "selectionOverlay"

    // 点击画布时请求关闭所有已打开的菜单（底部工具栏菜单 / 浮动工具栏二级菜单）
    signal closeMenusRequested()

    readonly property color selectionBlue: "#1E88E5"
    readonly property real handleR: 10      // 角把手圆半径（白填充/黑 1px 边框，深浅色一致）
    readonly property real handleHit: 16    // 角把手可点击半宽（视觉圆 + 外扩命中区）
    readonly property real edgeHit: 16      // 边框拖拽条带厚度（跨内外，避让四角把手；视觉宽度仍 2px）
    property bool circling: false           // 是否正在圈选（驱动 Canvas 显示与后端更新）

    // 交互可用：交互智能平板 + 选择工具 + 窗口可见
    property bool active: settingsBackend.getString("device_type") === "interactive_panel"
                         && lessonsBackend.activeTool === 0
    visible: active
    enabled: active
    z: 60

    // 圈选虚线 + 蓝色闭合填充（Canvas 实时绘制，仅圈选进行中显示）。
    // 虚线 = 沿闭合路径每隔 2px 画一个半径 1px 的圆（直径 2px，圆点间距 2px），
    // 精确满足"每段线是半径1px的圆、线间间隔2px"（Qt 不渲染零长度 dash，故手工画点）。
    Canvas {
        id: circleCanvas
        anchors.fill: parent
        visible: root.circling
        property var points: []
        onPointsChanged: requestPaint()
        function drawDots(ctx, pts) {
            ctx.fillStyle = root.selectionBlue
            var n = pts.length
            var dotDist = 0   // 距下一个圆点的沿路径距离（0,4,8,...）
            for (var i = 0; i < n; i++) {
                var x0 = pts[i][0], y0 = pts[i][1]
                var x1 = pts[(i + 1) % n][0], y1 = pts[(i + 1) % n][1]
                var dx = x1 - x0, dy = y1 - y0
                var seg = Math.hypot(dx, dy)
                if (seg < 1e-6) continue
                var ux = dx / seg, uy = dy / seg
                var d = dotDist
                while (d <= seg) {
                    ctx.beginPath()
                    ctx.arc(x0 + ux * d, y0 + uy * d, 1, 0, 2 * Math.PI)
                    ctx.fill()
                    d += 4   // 2px 圆点 + 2px 间隔
                }
                dotDist = d - seg
            }
        }
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            var pts = points
            if (!pts || pts.length < 3) return
            ctx.beginPath()
            ctx.moveTo(pts[0][0], pts[0][1])
            for (var i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1])
            ctx.closePath()   // 起点与终点相连形成闭合图形
            // 低透明度蓝色填充（封闭图形内部）
            ctx.fillStyle = "rgba(30,136,229,0.15)"
            ctx.fill()
            // 半径 1px 的圆点虚线（圆端头 ≈ 半径1px 的圆）
            drawDots(ctx, pts)
        }
    }

    // 全屏圈选 / 单击鼠标区（在矩形/把手之下：后者为更晚声明的兄弟，叠于其上）
    MouseArea {
        id: selArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        preventStealing: true
        property point pressStart: Qt.point(0, 0)
        property bool circling: false
        property var pts: []

        onPressed: {
            // 点击画布时关闭底部工具栏菜单与浮动工具栏二级菜单（由父级统一处理）
            root.closeMenusRequested()
            pressStart = Qt.point(mouse.x, mouse.y)
            circling = false
            root.circling = false
            pts = []
            circleCanvas.points = []
        }
        onPositionChanged: {
            var d = Math.hypot(mouse.x - pressStart.x, mouse.y - pressStart.y)
            if (d < 4) return          // 小于阈值视为单击
            if (!circling) {
                circling = true
                root.circling = true
                pts = [[pressStart.x, pressStart.y]]
                whiteboardBackend.beginSelection(pts)
            }
            var last = pts[pts.length - 1]
            if (Math.hypot(mouse.x - last[0], mouse.y - last[1]) >= 2) {
                pts.push([mouse.x, mouse.y])
            }
            whiteboardBackend.updateSelection(pts)
            circleCanvas.points = pts.slice()
        }
        onReleased: {
            if (circling) {
                whiteboardBackend.endSelection()
            } else {
                whiteboardBackend.clickSelect(mouse.x, mouse.y)
            }
            circling = false
            root.circling = false
            pts = []
            circleCanvas.points = []
        }
        onCanceled: {
            circling = false
            root.circling = false
            pts = []
            circleCanvas.points = []
            whiteboardBackend.cancelSelection()
        }
    }

    // 确认选择后的边界矩形 + 四角把手 + 边框拖拽条带
    Item {
        id: selRectUI
        visible: whiteboardBackend.hasSelection
        x: whiteboardBackend.selectionRect.length >= 4 ? whiteboardBackend.selectionRect[0] : 0
        y: whiteboardBackend.selectionRect.length >= 4 ? whiteboardBackend.selectionRect[1] : 0
        width: whiteboardBackend.selectionRect.length >= 4 ? whiteboardBackend.selectionRect[2] : 0
        height: whiteboardBackend.selectionRect.length >= 4 ? whiteboardBackend.selectionRect[3] : 0

        // 2px 蓝色边框矩形（无填充）
        Rectangle {
            anchors.fill: parent
            color: "transparent"
            border.width: 2
            border.color: root.selectionBlue
        }

        // 矩形内部区域拖拽 = 平移（视觉无变化；边框条带/四角把手在其上优先）
        MouseArea {
            id: innerMoveArea
            objectName: "innerMoveArea"
            anchors.fill: parent
            cursorShape: Qt.SizeAllCursor
            onPressed: (m) => { root.beginMove(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.moveTo(mapToItem(root, m.x, m.y)) }
            onReleased: root.endMove()
            onCanceled: root.endMove()
        }

        // 顶部边框拖拽条带（跨内外：中心在边框线上、向两侧各延伸 edgeHit/2；避让四角把手）
        MouseArea {
            id: topEdge
            objectName: "edge_top"
            x: root.handleHit
            y: -root.edgeHit / 2
            width: parent.width - root.handleHit * 2
            height: root.edgeHit
            cursorShape: Qt.SizeVerCursor
            onPressed: (m) => { root.beginMove(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.moveTo(mapToItem(root, m.x, m.y)) }
            onReleased: root.endMove()
        }
        // 底部边框拖拽条带
        MouseArea {
            id: bottomEdge
            x: root.handleHit
            y: parent.height - root.edgeHit / 2
            width: parent.width - root.handleHit * 2
            height: root.edgeHit
            cursorShape: Qt.SizeVerCursor
            onPressed: (m) => { root.beginMove(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.moveTo(mapToItem(root, m.x, m.y)) }
            onReleased: root.endMove()
        }
        // 左侧边框拖拽条带
        MouseArea {
            id: leftEdge
            x: -root.edgeHit / 2
            y: root.handleHit
            width: root.edgeHit
            height: parent.height - root.handleHit * 2
            cursorShape: Qt.SizeHorCursor
            onPressed: (m) => { root.beginMove(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.moveTo(mapToItem(root, m.x, m.y)) }
            onReleased: root.endMove()
        }
        // 右侧边框拖拽条带
        MouseArea {
            id: rightEdge
            x: parent.width - root.edgeHit / 2
            y: root.handleHit
            width: root.edgeHit
            height: parent.height - root.handleHit * 2
            cursorShape: Qt.SizeHorCursor
            onPressed: (m) => { root.beginMove(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.moveTo(mapToItem(root, m.x, m.y)) }
            onReleased: root.endMove()
        }

        // 四角把手：白色填充 + 黑色 1px 边框圆（r10），拖拽等比缩放（锚定对角）
        component CornerHandle: Item {
            property string corner: "tl"
            width: root.handleHit * 2
            height: root.handleHit * 2
            Rectangle {
                anchors.centerIn: parent
                width: root.handleR * 2
                height: root.handleR * 2
                radius: root.handleR
                color: "white"
                border.width: 1
                border.color: "black"
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SizeFDiagCursor
                onPressed: (m) => { root.beginScale(corner) }
                onPositionChanged: (m) => { root.scaleTo(mapToItem(root, m.x, m.y)) }
                onReleased: root.endScale()
                objectName: "cornerHandle_" + corner
            }
        }
        CornerHandle { corner: "tl"; x: -root.handleHit; y: -root.handleHit }
        CornerHandle { corner: "tr"; x: parent.width - root.handleHit; y: -root.handleHit }
        CornerHandle { corner: "br"; x: parent.width - root.handleHit; y: parent.height - root.handleHit }
        CornerHandle { corner: "bl"; x: -root.handleHit; y: parent.height - root.handleHit }
    }

    // ---------- 拖拽逻辑 ----------
    // 每次事件都以"后端当前选择矩形"为基准做增量映射（后端 applyTransform 用自身
    // _sel_rect），连续拖拽多次事件不会累积误差，笔迹与矩形严格同步跟随鼠标。
    // 一次拖拽（按下→松开）由 beginModify/endModify 合并为一次撤销。
    // _dragState: {mode:"move", startRect, gStart} | {mode:"scale", corner, startRect, anchorX, anchorY, aspect}
    property var _dragState: null

    function _readRect() {
        var r = whiteboardBackend.selectionRect
        return (r && r.length >= 4) ? r : null
    }

    function beginMove(gp) {
        var r = _readRect()
        if (!r) return
        _dragState = { mode: "move",
                       startRect: [r[0], r[1], r[2], r[3]],
                       gStart: Qt.point(gp.x, gp.y) }
        whiteboardBackend.beginModify()
    }
    function moveTo(gp) {
        if (!_dragState || _dragState.mode !== "move") return
        var sr = _dragState.startRect
        var dx = gp.x - _dragState.gStart.x
        var dy = gp.y - _dragState.gStart.y
        var nl = Math.max(0, Math.min(root.width - sr[2], sr[0] + dx))
        var nt = Math.max(0, Math.min(root.height - sr[3], sr[1] + dy))
        whiteboardBackend.applyTransform(nl, nt, sr[2], sr[3])
    }
    function endMove() {
        whiteboardBackend.endModify()
        _dragState = null
    }

    // 缩放：锚定对角（拖哪个角，对角在原位置不动），严格保持长宽比；
    // 看鼠标到锚点的 xy 距离（归一化后）哪个坐标"较短"，被拖角就跟随该坐标，
    // 另一坐标按原长宽比推导 → 角点不脱离鼠标的同时长宽比不变。
    function beginScale(corner) {
        var r = _readRect()
        if (!r) return
        _dragState = { mode: "scale", corner: corner,
                       startRect: [r[0], r[1], r[2], r[3]] }
        // 锚点 = 对角（tl/bl 在左缘 → 锚右缘；tr/br 在右缘 → 锚左缘；
        //            tl/tr 在上缘 → 锚下缘；bl/br 在下缘 → 锚上缘）
        _dragState.anchorX = (corner === "tl" || corner === "bl") ? r[0] + r[2] : r[0]
        _dragState.anchorY = (corner === "tl" || corner === "tr") ? r[1] + r[3] : r[1]
        _dragState.aspect = r[2] / r[3]   // 原长宽比（整次拖拽固定）
        whiteboardBackend.beginModify()
    }
    function scaleTo(gp) {
        if (!_dragState || _dragState.mode !== "scale") return
        var ax = _dragState.anchorX
        var ay = _dragState.anchorY
        var sx = (_dragState.corner === "tl" || _dragState.corner === "bl") ? -1 : 1
        var sy = (_dragState.corner === "tl" || _dragState.corner === "tr") ? -1 : 1
        var aspect = _dragState.aspect
        var w0 = _dragState.startRect[2], h0 = _dragState.startRect[3]
        var distX = Math.abs(gp.x - ax)
        var distY = Math.abs(gp.y - ay)
        var minSize = 8
        var nw, nh
        // 归一化比较（相对原尺寸）：哪个坐标移动较短，被拖角就跟随哪个坐标
        if (w0 > 0 && h0 > 0 && distX / w0 <= distY / h0) {
            nw = Math.max(distX, minSize)
            nh = nw / aspect
        } else {
            nh = Math.max(distY, minSize)
            nw = nh * aspect
        }
        var nl = sx < 0 ? ax - nw : ax
        var nt = sy < 0 ? ay - nh : ay
        nl = Math.max(0, Math.min(root.width - nw, nl))
        nt = Math.max(0, Math.min(root.height - nh, nt))
        whiteboardBackend.applyTransform(nl, nt, nw, nh)
    }
    function endScale() {
        whiteboardBackend.endModify()
        _dragState = null
    }
}
