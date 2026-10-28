import QtQuick 2.15
import RinUI

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

    // 形状线端点手柄模式：选中项**全是形状线**时，除了“蓝色矩形 + 四角缩放手柄”，
    // 还给每条线（坐标系只给**箭头端**）一个圆手柄拖端点（旋转手柄两种形态下都在）。
    // 含手绘笔迹的混选返回空 → 只有传统矩形形态。
    readonly property var lineHandles: whiteboardBackend.selectionLineHandles
    readonly property bool lineMode: lineHandles !== undefined && lineHandles !== null
                                     && lineHandles.length > 0
    // 端点手柄拖拽中（一次拖拽合并为一次撤销）
    property bool _endDrag: false

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
            // 批量绘制：所有圆点收进同一条 Path 后只 fill 一次（原来每个圆点
            // 一次 beginPath+arc+fill，长圈选路径每帧可积累上千次调用 → 明显卡顿）。
            // 每个圆点前先 moveTo(圆心+r, 圆心) 断开子路径，避免被连成折线。
            ctx.fillStyle = root.selectionBlue
            ctx.beginPath()
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
                    var cx = x0 + ux * d, cy = y0 + uy * d
                    ctx.moveTo(cx + 1, cy)
                    ctx.arc(cx, cy, 1, 0, 2 * Math.PI)
                    d += 4   // 2px 圆点 + 2px 间隔
                }
                dotDist = d - seg
            }
            ctx.fill()
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
            // 形状线端点手柄命中 → 进入端点拖拽（本 MouseArea 全程持有 grab，
            // 不会因手柄项被 Repeater 重建而中断）
            root.tryBeginEndDrag(Qt.point(mouse.x, mouse.y))
        }
        onPositionChanged: {
            if (root._endDrag) {
                root.endDragTo(Qt.point(mouse.x, mouse.y))
                return
            }
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
            if (root._endDrag) {
                root.endEndDrag()
                return
            }
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
            if (root._endDrag) {
                root.endEndDrag()
                return
            }
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
        // 选中框姿态（顺时针正）：persistRot = 本选择累计旋转角（backend，重选归 0）；
        // dragDelta = 旋转拖拽中的增量；整框（含边框/四角把手/旋转圆）绕矩形中心旋转显示
        property real persistRot: 0
        property real dragDelta: 0
        rotation: persistRot + dragDelta
        transformOrigin: Item.Center

        // 2px 蓝色边框矩形（无填充）；形状线端点手柄模式下也显示（用户要求 4：
        // 选中的全是线/坐标系时同样要有矩形框 + 四角缩放手柄，功能与笔迹选择一致）
        Rectangle {
            objectName: "selBorder"
            anchors.fill: parent
            color: "transparent"
            border.width: 2
            border.color: root.selectionBlue
        }

        // 矩形内部区域拖拽 = 平移（视觉无变化；边框条带/四角把手在其上优先）。
        // 按下处若命中了端点手柄（形状线/坐标系）→ 优先拖端点（见 tryBeginEndDrag）。
        MouseArea {
            id: innerMoveArea
            objectName: "innerMoveArea"
            anchors.fill: parent
            cursorShape: Qt.SizeAllCursor
            onPressed: (m) => { root.pressMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.dragMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onReleased: root.releaseMoveOrEnd()
            onCanceled: root.releaseMoveOrEnd()
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
            onPressed: (m) => { root.pressMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.dragMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onReleased: root.releaseMoveOrEnd()
            onCanceled: root.releaseMoveOrEnd()
        }
        // 底部边框拖拽条带
        MouseArea {
            id: bottomEdge
            objectName: "edge_bottom"
            x: root.handleHit
            y: parent.height - root.edgeHit / 2
            width: parent.width - root.handleHit * 2
            height: root.edgeHit
            cursorShape: Qt.SizeVerCursor
            onPressed: (m) => { root.pressMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.dragMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onReleased: root.releaseMoveOrEnd()
            onCanceled: root.releaseMoveOrEnd()
        }
        // 左侧边框拖拽条带
        MouseArea {
            id: leftEdge
            objectName: "edge_left"
            x: -root.edgeHit / 2
            y: root.handleHit
            width: root.edgeHit
            height: parent.height - root.handleHit * 2
            cursorShape: Qt.SizeHorCursor
            onPressed: (m) => { root.pressMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.dragMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onReleased: root.releaseMoveOrEnd()
            onCanceled: root.releaseMoveOrEnd()
        }
        // 右侧边框拖拽条带
        MouseArea {
            id: rightEdge
            objectName: "edge_right"
            x: parent.width - root.edgeHit / 2
            y: root.handleHit
            width: root.edgeHit
            height: parent.height - root.handleHit * 2
            cursorShape: Qt.SizeHorCursor
            onPressed: (m) => { root.pressMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onPositionChanged: (m) => { root.dragMoveOrEnd(mapToItem(root, m.x, m.y)) }
            onReleased: root.releaseMoveOrEnd()
            onCanceled: root.releaseMoveOrEnd()
        }

        // 四角把手：白色填充 + 黑色 1px 边框圆（r10）；拖拽以对角为锚**自由比例**缩放，
        // 鼠标靠近"等比例缩放直线"时吸附到该线上（蓝色虚线提示 + 宽高比 = 原比例）。
        // 形状线端点手柄模式下也显示（与蓝色矩形框一致）；但若按下处恰好命中了某个
        // 端点手柄，则优先走端点拖拽（否则端点落在角上时就再也拖不动它了）。
        component CornerHandle: Item {
            id: cornerRoot
            property string corner: "tl"
            property bool endDrag: false       // 本次拖拽走的是"端点手柄"而不是缩放
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
                onPressed: (m) => {
                    var g = mapToItem(root, m.x, m.y)
                    cornerRoot.endDrag = root.tryBeginEndDrag(g)
                    if (!cornerRoot.endDrag) root.beginScale(cornerRoot.corner)
                }
                onPositionChanged: (m) => {
                    var g = mapToItem(root, m.x, m.y)
                    if (cornerRoot.endDrag) root.endDragTo(g)
                    else root.scaleTo(g)
                }
                onReleased: {
                    if (cornerRoot.endDrag) { cornerRoot.endDrag = false; root.endEndDrag() }
                    else root.endScale()
                }
                onCanceled: {
                    if (cornerRoot.endDrag) { cornerRoot.endDrag = false; root.endEndDrag() }
                    else root.endScale()
                }
                objectName: "cornerHandle_" + cornerRoot.corner
            }
        }
        CornerHandle { corner: "tl"; x: -root.handleHit; y: -root.handleHit }
        CornerHandle { corner: "tr"; x: parent.width - root.handleHit; y: -root.handleHit }
        CornerHandle { corner: "br"; x: parent.width - root.handleHit; y: parent.height - root.handleHit }
        CornerHandle { corner: "bl"; x: -root.handleHit; y: parent.height - root.handleHit }

        // 旋转圆把手：位于选中矩形顶边中点上方（随框旋转而转动）；比四角圆稍大，
        // 1px 半透明白边框(75%) + 半透明黑填充(60%) + 白色旋转图标（深浅色均此样式）
        Item {
            id: rotateHandle
            objectName: "rotateHandle"
            readonly property real hitR: 15     // 命中半径（略大于视觉圆）
            readonly property real visR: 13     // 视觉圆半径（比四角圆 r10 稍大）
            x: parent.width / 2 - hitR
            y: -hitR * 2 - 8
            width: hitR * 2
            height: hitR * 2

            Rectangle {
                anchors.centerIn: parent
                width: rotateHandle.visR * 2
                height: rotateHandle.visR * 2
                radius: rotateHandle.visR
                color: "#99000000"            // 黑 60%
                border.width: 1
                border.color: "#BFFFFFFF"      // 白 75%
            }
            Icon {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: 1
                name: "ic_fluent_arrow_rotate_clockwise_20_regular"
                size: 20
                color: "#FFFFFF"
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SizeAllCursor
                onPressed: (m) => root.startRotate(mapToItem(root, m.x, m.y))
                onPositionChanged: (m) => root.rotateDrag(mapToItem(root, m.x, m.y))
                onReleased: root.stopRotate()
                onCanceled: root.stopRotate()
            }
        }
    }

    // ---------- 形状线端点手柄层 ----------
    // 绝对坐标（画布坐标系）：每条选中线两个圆手柄（起点/终点），直接反映后端真实端点
    // → 旋转后自动跟随几何，无需额外变换。层级在 selRectUI 之后 → 压在平移区之上。
    // 旋转拖拽中（预览未改数据）暂时隐藏，避免手柄位置与预览不一致。
    Item {
        id: lineHandlesUI
        objectName: "lineHandlesUI"
        anchors.fill: parent
        visible: root.active && root.lineMode && selRectUI.dragDelta === 0

        component EndHandle: Item {
            id: endHandle
            objectName: "endHandle"
            property int sid: 0        // 目标线笔划 id
            property int which: 0      // 0=起点 1=终点
            property real hx: 0        // 端点画布坐标
            property real hy: 0
            readonly property real visR: 9    // 视觉圆半径（比四角圆略小，每条线两个）
            readonly property real hitR: 16   // 命中半宽（含外扩）
            x: hx - hitR
            y: hy - hitR
            width: hitR * 2
            height: hitR * 2
            Rectangle {
                anchors.centerIn: parent
                width: endHandle.visR * 2
                height: endHandle.visR * 2
                radius: endHandle.visR
                color: "white"
                border.width: 1
                border.color: "black"
            }
            // 手柄**纯视觉**：绝不在这里挂接收按键的 MouseArea。
            // 该 Item 会随 lineHandles 模型变化被 Repeater 重建，挂在它上面的
            // MouseArea 会在拖拽中途被销毁、丢掉鼠标 grab → 表现为“端点只能动几px”。
            // 拖拽统一由覆盖层稳定的 selArea / innerMoveArea 经
            // whiteboardBackend.hitLineEndpoint(x,y) 命中后分发。
            // 下面这个不接按键的 MouseArea 仅用于指针形状（不拦下层事件）。
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                hoverEnabled: true
                cursorShape: Qt.SizeAllCursor
            }
        }

        Repeater {
            model: root.lineHandles
            delegate: Item {
                required property var modelData
                // 坐标系：哪一端有手柄由后端 has0/has1 决定（空间直角坐标系原点那一端不给，
                // 平面直角坐标系两端都给）
                EndHandle {
                    sid: modelData.id
                    which: 0
                    hx: modelData.x0
                    hy: modelData.y0
                    visible: modelData.has0 !== false
                }
                EndHandle {
                    sid: modelData.id
                    which: 1
                    hx: modelData.x1
                    hy: modelData.y1
                    visible: modelData.has1 !== false
                }
            }
        }
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

    // ---------- 形状线端点手柄拖拽 ----------
    // 一次按下→松开 = 一次可撤销的 modify（后端 beginLineHandle 做快照，
    // endLineHandle 比对旧数据后压 undo 并落盘）。
    // 命中检测放后端（按端点半径 16）：手柄项本身不接事件（见 EndHandle 注释）。
    // 坐标系（未被橡皮破坏）只能拖**箭头端**，且只能沿该轴原方向、不得越过原点（后端约束）。
    function tryBeginEndDrag(gp) {
        if (!root.active || !root.lineMode) return false
        var h = whiteboardBackend.hitLineEndpoint(gp.x, gp.y)
        if (!h || h.length !== 2) return false
        _endDrag = true
        whiteboardBackend.beginLineHandle(h[0], h[1])
        return true
    }
    // 统一的“按下/拖动/松开”分发：先试端点手柄，否则平移（供内区/四条边框/四角共用）
    function pressMoveOrEnd(gp) {
        if (!root.tryBeginEndDrag(gp)) root.beginMove(gp)
    }
    function dragMoveOrEnd(gp) {
        if (root._endDrag) root.endDragTo(gp)
        else root.moveTo(gp)
    }
    function releaseMoveOrEnd() {
        if (root._endDrag) root.endEndDrag()
        else root.endMove()
    }
    function endDragTo(gp) {
        if (!_endDrag) return
        whiteboardBackend.dragLineHandle(gp.x, gp.y)
    }
    function endEndDrag() {
        if (!_endDrag) return
        _endDrag = false
        whiteboardBackend.endLineHandle()
    }

    // 缩放：锚定对角（拖哪个角，对角在原位置不动），**任意长宽比**（不再等比）；
    // 被拖角直接跟随鼠标的 x/y（各轴独立，各自有最小尺寸限制）。
    function beginScale(corner) {
        var r = _readRect()
        if (!r) return
        // 缩放开始：先清掉上一次可能残留的"等比例缩放直线"虚线
        whiteboardBackend.clearScaleAspectGuide()
        // 旋转态（框有姿态角）：点阵锚定缩放由后端在旋转参考系处理，保持当前旋转角
        if (Math.abs(Number(whiteboardBackend.selectionRotation) || 0) > 0.01) {
            _dragState = { mode: "rscale", corner: corner }
            whiteboardBackend.beginRotatedScale(corner)
            return
        }
        _dragState = { mode: "scale", corner: corner,
                       startRect: [r[0], r[1], r[2], r[3]] }
        // 锚点 = 对角（tl/bl 在左缘 → 锚右缘；tr/br 在右缘 → 锚左缘；
        //            tl/tr 在上缘 → 锚下缘；bl/br 在下缘 → 锚上缘）
        _dragState.anchorX = (corner === "tl" || corner === "bl") ? r[0] + r[2] : r[0]
        _dragState.anchorY = (corner === "tl" || corner === "tr") ? r[1] + r[3] : r[1]
        whiteboardBackend.beginModify()
    }
    function scaleTo(gp) {
        if (!_dragState) return
        if (_dragState.mode === "rscale") {
            whiteboardBackend.rotatedScaleTo(gp.x, gp.y)
            return
        }
        if (_dragState.mode !== "scale") return
        // 等比例缩放直线吸附：鼠标靠近该线时，被拖角就近吸到线上（宽高比 = 原比例）
        var sr0 = _dragState.startRect
        var sp = whiteboardBackend.snapScaleAspect(gp.x, gp.y, _dragState.corner,
                                                   sr0[0], sr0[1], sr0[2], sr0[3])
        var mx = (sp && sp.length >= 2) ? sp[0] : gp.x
        var my = (sp && sp.length >= 2) ? sp[1] : gp.y
        var ax = _dragState.anchorX
        var ay = _dragState.anchorY
        var sx = (_dragState.corner === "tl" || _dragState.corner === "bl") ? -1 : 1
        var sy = (_dragState.corner === "tl" || _dragState.corner === "tr") ? -1 : 1
        var minSize = 8
        // 各轴独立跟随鼠标（自由比例缩放）
        var nw = Math.max(Math.abs(mx - ax), minSize)
        var nh = Math.max(Math.abs(my - ay), minSize)
        var nl = sx < 0 ? ax - nw : ax
        var nt = sy < 0 ? ay - nh : ay
        nl = Math.max(0, Math.min(root.width - nw, nl))
        nt = Math.max(0, Math.min(root.height - nh, nt))
        whiteboardBackend.applyTransform(nl, nt, nw, nh)
    }
    function endScale() {
        if (_dragState && _dragState.mode === "rscale")
            whiteboardBackend.endRotatedScale()
        else
            whiteboardBackend.endModify()
        whiteboardBackend.clearScaleAspectGuide()   // 缩放结束 → 收起等比例虚线
        _dragState = null
    }

    // 旋转：以选中矩形几何中心为旋转中心，鼠标绕该中心的角度增量驱动旋转。
    // 拖拽中整框以 persistRot+dragDelta 显示并与后端预览同步；松手后端提交向量旋转并
    // 把角度并入选择姿态（框保持旋转、不重包围，悬浮工具栏位置不动），直到下次重选归零。
    // 一次拖拽合并为一次撤销（modify）。
    property var _rotDrag: null   // {cx, cy, startAngle}

    // 从后端同步本选择姿态角（重选/清除时归 0）；拖拽中由 dragDelta 叠加显示
    function syncRot() {
        selRectUI.dragDelta = 0
        selRectUI.persistRot = whiteboardBackend.hasSelection
            ? (Number(whiteboardBackend.selectionRotation) || 0)
            : 0
    }

    function startRotate(gp) {
        var r = _readRect()
        if (!r || r[2] <= 0 || r[3] <= 0) return
        var cx = r[0] + r[2] / 2
        var cy = r[1] + r[3] / 2
        _rotDrag = { cx: cx, cy: cy,
                     start: Math.atan2(gp.y - cy, gp.x - cx) * 180 / Math.PI }
        whiteboardBackend.beginRotate()
    }
    function rotateDrag(gp) {
        if (!_rotDrag) return
        var a = Math.atan2(gp.y - _rotDrag.cy, gp.x - _rotDrag.cx) * 180 / Math.PI
        var d = a - _rotDrag.start
        if (d > 180) d -= 360
        else if (d < -180) d += 360
        selRectUI.dragDelta = d      // 显示 = persistRot + d
        whiteboardBackend.rotatePreview(d)
    }
    function stopRotate() {
        if (!_rotDrag) return
        _rotDrag = null
        whiteboardBackend.endRotate()   // 同步 emit selectionChanged → syncRot 更新姿态
        syncRot()                        // 兜底同步（框停在旋转后的姿态）
    }

    // 选择变化（新选/清除/旋转提交等）→ 同步框姿态角
    Connections {
        target: whiteboardBackend
        function onSelectionChanged() { root.syncRot() }
    }
    Component.onCompleted: syncRot()
}
