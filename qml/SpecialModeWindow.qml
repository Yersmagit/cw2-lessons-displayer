import QtQuick 2.15
import RinUI
import QtQuick.Window 2.15
// 手写板功能前端组件（底部工具栏/笔与橡皮菜单/页面列表/选择工具/圆按钮）已整理到子目录 specialmode，
// 经相对目录导入后 SelectionOverlay/SelectionToolbar/SpecialModeToolbar 等类型可直接实例化。
import "specialmode"

// QtQuick.Window 必须在 RinUI 之后 import：否则根 Window 会被解析为 RinUI 的 Window
// （windows/window/Window.qml，带 CtrlBtn 系统窗口控件：最小化/关闭），从而出现窗口控件。

// 特殊模式（白板/熄屏）专用全屏窗口：进入时隐藏创建，动画完成后由 Python 端
// show()+FullScreen 直接显示（无渐变动画）全屏置顶；不能写 visibility:FullScreen（会覆盖 visible:false 创建即显示）。
Window {
    id: root
    visible: false
    // 不用 QML flags 常量：某些真实环境创建时 QML 常量 flags 未即时生效会露出系统标题栏；
    // 窗口样式完全由 Python 端 setFlags 控制（_prepare_special_window 创建即强制 + 显示时再强制 + _force_topmost 兜底）
    color: "transparent"
    x: 0
    y: 0
    width: Screen.width
    height: Screen.height

    // 背景层（纯色）
    Rectangle {
        id: backgroundLayer
        anchors.fill: parent
        color: lessonsBackend.mode === "whiteboard" ? "white" : "black"
        Behavior on color {
            ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
        }
    }

    // 笔迹显示（仅交互智能平板）：在背景之上、课程条之上（可遮挡课程列表），
    // 但仍在右键菜单/工具栏之下。由 Python WhiteboardBackend 烘焙 QImage，经
    // image://whiteboard 提供；每次笔迹变化 backend.imageVersion 递增触发 source 刷新。
    Image {
        id: whiteboardImg
        objectName: "whiteboardImg"
        anchors.fill: parent
        visible: settingsBackend.getString("device_type") === "interactive_panel"
        source: "image://whiteboard/canvas?v=" + whiteboardBackend.imageVersion
        z: 40
        smooth: true
    }

    // 橡皮指示圆（按下时跟随鼠标：白色填充 + 黑色 1px 边框，半径 16px，深浅色一致）
    Rectangle {
        id: eraserIndicator
        objectName: "eraserIndicator"
        width: 32
        height: 32
        radius: 16
        color: "white"
        border.width: 1
        border.color: "black"
        z: 45
        visible: settingsBackend.getString("device_type") === "interactive_panel"
                 && lessonsBackend.activeTool === 2 && drawingArea.penDown
        x: drawingArea.lastPt.x - width / 2
        y: drawingArea.lastPt.y - height / 2
    }

    // 蓝色 1px 虚线引导线（多处共用同一个 Canvas，颜色与选中蓝边一致）：
    //   ① 图形绘制的"可等边直线"吸附（后端 figureSnapGuide）；
    //   ② 圆的绘制过程中的半径；
    //   ③ 椭圆：第一阶段的两焦点连线 / 第二阶段 探针→两焦点 两条连线；
    //   ④ 选中笔迹四角缩放时的"等比例缩放直线"（后端 scaleAspectGuide）；
    //   ⑤ 多边形随心画的"缺口连线"（两端未连线端点之间）——它被等长/平行吸附命中时
    //      改画成"笔迹颜色/粗细的虚线 + 外侧 2px 蓝"（见下面的 gapInk 分支）。
    // 后端给的是"扁平的多段" [x0,y0,x1,y1, x0,y0,x1,y1, ...]；未吸附/未拖拽时不显示。
    // 虚线分段手绘（Canvas 的 setLineDash 不可靠）。
    Canvas {
        id: figureSnapGuide
        objectName: "figureSnapGuide"
        anchors.fill: parent
        z: 46
        property var guide: {
            var g = whiteboardBackend.figureSnapGuide
            if (g !== undefined && g !== null && g.length >= 4) return g
            var s = whiteboardBackend.scaleAspectGuide
            return (s !== undefined && s !== null && s.length >= 4) ? s : []
        }
        readonly property color guideColor: "#1E88E5"      // = SELECTION_BLUE
        // 命中的是"缺口连线"（多边形随心画被等长/平行吸附）时，**不再画成加粗的蓝虚线**，
        // 而是按用户要求：**用笔迹的颜色、粗细**在这个缺口处画一条**实线**（预告"闭合后会
        // 生成的那条边"），并在其**外侧描 2px 蓝**；实线与描边都用 **60% 不透明度**
        //（先按"线宽 + 4"铺蓝底、再把笔迹色盖回中间，与命中边的蓝色 2px 描边同一套画法）。
        readonly property bool gapInk: whiteboardBackend.figureSnapBoldGuide === true
                                       && String(whiteboardBackend.figureGapColor || "") !== ""
        readonly property real gapW: Math.max(0.5, whiteboardBackend.figureGapWidth || 4.0)
        readonly property real gapAlpha: 0.6        // 缺口实线 + 蓝描边的不透明度（用户要求）
        readonly property int guideWidth: 1
        readonly property int dashLen: 7
        readonly property int gapLen: 6
        visible: guide !== undefined && guide !== null && guide.length >= 4
        onGuideChanged: requestPaint()
        onGapInkChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: requestPaint()
        Component.onCompleted: requestPaint()
        // 沿一条线段按"划 / 空"逐段手绘（Canvas 的 setLineDash 不可靠）
        function dashLine(ctx, x0, y0, x1, y1, dashPx, gapPx) {
            var dx = x1 - x0, dy = y1 - y0
            var len = Math.hypot(dx, dy)
            if (len < 1) return
            var ux = dx / len, uy = dy / len
            var t = 0
            while (t < len) {
                var e = Math.min(len, t + dashPx)
                ctx.beginPath()
                ctx.moveTo(x0 + ux * t, y0 + uy * t)
                ctx.lineTo(x0 + ux * e, y0 + uy * e)
                ctx.stroke()
                t = e + gapPx
            }
        }
        onPaint: {
            var ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            if (!visible) return
            var n = Math.floor(guide.length / 4)
            var s
            if (gapInk) {
                // 缺口连线：笔迹色**实线** + **外侧** 2px 蓝，两者都 60% 不透明度。
                // 做法（真"描边"而不是"垫底"）：先按 w+4 铺蓝 → destination-out 擦掉中间 w 的带
                //（只在本 Canvas 上留外侧各 2px 蓝，不影响画布图）→ 再画笔迹色实线（w）。
                // 这样半透明笔迹不会被蓝色垫底"染蓝"，颜色就是 60% 的笔迹色（用户要求）。
                ctx.lineCap = "round"
                ctx.globalAlpha = gapAlpha
                ctx.strokeStyle = guideColor
                ctx.lineWidth = gapW + 4.0
                for (s = 0; s < n; s++) {
                    ctx.beginPath()
                    ctx.moveTo(guide[s * 4], guide[s * 4 + 1])
                    ctx.lineTo(guide[s * 4 + 2], guide[s * 4 + 3])
                    ctx.stroke()
                }
                ctx.globalCompositeOperation = "destination-out"
                ctx.lineWidth = gapW
                for (s = 0; s < n; s++) {
                    ctx.beginPath()
                    ctx.moveTo(guide[s * 4], guide[s * 4 + 1])
                    ctx.lineTo(guide[s * 4 + 2], guide[s * 4 + 3])
                    ctx.stroke()
                }
                ctx.globalCompositeOperation = "source-over"
                ctx.strokeStyle = whiteboardBackend.figureGapColor
                ctx.lineWidth = gapW
                for (s = 0; s < n; s++) {
                    ctx.beginPath()
                    ctx.moveTo(guide[s * 4], guide[s * 4 + 1])
                    ctx.lineTo(guide[s * 4 + 2], guide[s * 4 + 3])
                    ctx.stroke()
                }
                ctx.globalAlpha = 1.0
                return
            }
            ctx.lineWidth = guideWidth
            ctx.lineCap = "butt"
            ctx.strokeStyle = guideColor
            for (s = 0; s < n; s++) {
                dashLine(ctx, guide[s * 4], guide[s * 4 + 1],
                         guide[s * 4 + 2], guide[s * 4 + 3], dashLen, gapLen)
            }
        }
    }

    // 等边吸附 / 焦点 / 渐近线提示胶囊：虚线边框 + 左侧小图形 + 名称。
    // 显示时机：形状绘制中（penDown）或正在拖两阶段图形的焦点/端点手柄（focusProbeDragging）；
    // 位置：拖手柄时用后端探针位置（鼠标就在手柄上），否则鼠标上方 26px。
    // （多边形随心画的**夹角文字**是另一颗胶囊，见下面的 angleHint；
    //   等长/平行吸附的两条边蓝色 2px 描边由后端画进画布图，见 main.py `_draw_pf_highlight`。）
    SnapHint {
        id: snapHint
        objectName: "snapHint"
        z: 47
        readonly property bool probeDragging: whiteboardBackend.focusProbeDragging === true
        readonly property string iconKind: visible
                                           ? String(whiteboardBackend.figureSnapIconKind || "") : ""
        visible: (drawingArea.penDown || probeDragging)
                 && String(whiteboardBackend.figureSnapKind || "") !== ""
        showIcon: iconKind !== ""
        shapeKind: iconKind
        label: visible ? whiteboardBackend.figureSnapName : ""
        shapesAspect: {
            var m = whiteboardBackend.shapeAspects
            return (m && m[shapeKind] !== undefined) ? m[shapeKind] : 1.0
        }
        lightMode: lessonsBackend.mode === "whiteboard"
        // 提示锚点：拖手柄时用后端探针位置（绘制区的 lastPt 此时是旧值），否则鼠标位置
        readonly property point anchorPt: {
            if (probeDragging) {
                var p = whiteboardBackend.focusProbePoint
                if (p && p.length >= 2) return Qt.point(p[0], p[1])
            }
            return drawingArea.lastPt
        }
        // 鼠标上方 26px、水平居中于鼠标；夹在窗口内
        x: Math.max(4, Math.min(root.width - width - 4, anchorPt.x - width / 2))
        y: Math.max(4, anchorPt.y - height - 26)
    }

    // 夹角角度提示胶囊（多边形随心画）：**无小图标**、只有「xx°」。
    // 位置：后端 figureAngleAnchor = 内角平分线上距顶点**固定 28px** 的一点 → 胶囊**以该点为中心**
    //（于是胶囊几何中心恒好在角平分线上、距顶点 28px；不管当前是闭合/平行/等长/纯角度吸附都显示）。
    SnapHint {
        id: angleHint
        objectName: "angleHint"
        z: 49
        readonly property var anchor: whiteboardBackend.figureAngleAnchor
        readonly property bool hasAnchor: anchor !== undefined && anchor !== null
                                          && anchor.length >= 2
        visible: (drawingArea.penDown || snapHint.probeDragging)
                 && hasAnchor
                 && String(whiteboardBackend.figureAngleText || "") !== ""
        showIcon: false
        shapeKind: ""
        label: visible ? whiteboardBackend.figureAngleText : ""
        lightMode: lessonsBackend.mode === "whiteboard"
        x: hasAnchor ? Math.max(4, Math.min(root.width - width - 4, anchor[0] - width / 2)) : 0
        y: hasAnchor ? Math.max(4, Math.min(root.height - height - 4, anchor[1] - height / 2)) : 0
    }

    // 横平竖直吸附的第二个提示（带小图标"两个指向两侧的箭头"，弹在已有提示的**上方**）：
    // · 椭圆/双曲线定焦点、抛物线定焦准距线段：两个提示上下叠放（提示文字「水平排列」/「竖直排列」）
    // · **画线型**（直线/虚线/波浪线/箭头/…）：没有主提示（figureSnapKind 为空），
    //   这个提示直接弹在鼠标上方 26px（提示文字「水平」/「竖直」）
    SnapHint {
        id: alignHint
        objectName: "alignHint"
        z: 48
        // ⚠️ 拖拽状态与锚点都必须用 `snapHint.xxx`（`probeDragging`/`anchorPt` 是主提示自己的
        // 属性，不是根级属性；直接写裸名会 ReferenceError → 拖手柄时第二个提示根本不显示）
        readonly property bool dragging: drawingArea.penDown || snapHint.probeDragging
        visible: dragging && String(whiteboardBackend.figureAlignKind || "") !== ""
        shapeKind: visible ? whiteboardBackend.figureAlignIcon : ""
        // 小图形按"等边"比例画（三角/正方形/圆等）；alignh/alignv 这类箭头不在表里 → 1.0
        shapesAspect: {
            var m2 = whiteboardBackend.shapeAspects
            return (m2 && m2[shapeKind] !== undefined) ? m2[shapeKind] : 1.0
        }
        label: visible ? whiteboardBackend.figureAlignName : ""
        lightMode: lessonsBackend.mode === "whiteboard"
        // ⚠️ 锚点要用 `snapHint.anchorPt`（anchorPt 是主提示自己的属性，不是根级属性）
        readonly property point pt: snapHint.anchorPt
        readonly property real baseY: snapHint.visible
                                      ? snapHint.y
                                      : Math.max(4, pt.y - height - 26)
        readonly property bool roomAbove: baseY - height - 6 >= 4
        x: snapHint.visible
           ? Math.max(4, Math.min(root.width - width - 4,
                                  snapHint.x + (snapHint.width - width) / 2))
           : Math.max(4, Math.min(root.width - width - 4, pt.x - width / 2))
        y: snapHint.visible
           ? (roomAbove ? (baseY - height - 6) : (baseY + height + 6))
           : baseY
    }

    // 绘制鼠标区：笔/橡皮/形状工具按下拖动绘制；层级在课程条之上（可在课程列表区域绘制），
    // 仍在工具栏/菜单/右键菜单之下（工具栏 z1000 优先），不响应右键（留给菜单）
    MouseArea {
        id: drawingArea
        objectName: "drawingArea"
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        preventStealing: true
        z: 50
        property bool penDown: false
        property point lastPt: Qt.point(0, 0)
        // 当前是否形状工具（3）：按下至松开 = 一条线，松开后由后端发 shapeFinished
        // 让工具自动回退到之前的选择/笔/橡皮（工具栏指示器随之原地渐隐/渐显）
        readonly property bool shapeMode: lessonsBackend.activeTool === 3
        enabled: settingsBackend.getString("device_type") === "interactive_panel"
                 && (lessonsBackend.activeTool === 1 || lessonsBackend.activeTool === 2
                     || lessonsBackend.activeTool === 3)
                 && root.visible
        onPressed: (mouse) => {
            if (mouse.button !== Qt.LeftButton) return
            // 点击画布时关闭已打开的工具栏菜单
            var tbi = toolbarLoader.item
            if (tbi && tbi.closeMenus) tbi.closeMenus()
            penDown = true
            lastPt = Qt.point(mouse.x, mouse.y)
            if (shapeMode) {
                // 形状线：粗细/颜色取笔工具的设置；线型取形状菜单当前选择
                whiteboardBackend.beginLine(lessonsBackend.lineStyle, lessonsBackend.penColor,
                                            lessonsBackend.penWidth, mouse.x, mouse.y)
            } else if (lessonsBackend.activeTool === 1) {
                whiteboardBackend.beginStroke(0, lessonsBackend.penColor, lessonsBackend.penWidth, mouse.x, mouse.y)
            } else {
                whiteboardBackend.beginStroke(1, "", 32, mouse.x, mouse.y)  // 橡皮直径 = 2*16px
            }
        }
        onPositionChanged: (mouse) => {
            if (!penDown) return
            if (Math.abs(mouse.x - lastPt.x) < 1 && Math.abs(mouse.y - lastPt.y) < 1) return
            lastPt = Qt.point(mouse.x, mouse.y)
            if (shapeMode) whiteboardBackend.moveLine(mouse.x, mouse.y)
            else whiteboardBackend.moveStroke(mouse.x, mouse.y)
        }
        onReleased: {
            if (!penDown) return
            penDown = false
            if (shapeMode) whiteboardBackend.endLine()
            else whiteboardBackend.endStroke()
        }
        onCanceled: {
            if (penDown) {
                penDown = false
                if (shapeMode) whiteboardBackend.endLine()
                else whiteboardBackend.endStroke()
            }
        }
    }

    // 选择工具覆盖层（圈选虚线/填充/边界矩形/四角把手/边框拖拽）：
    // 层级在绘制区之上、底部工具栏/右键菜单/设置蒙层之下；仅"选择"工具时交互。
    // 点击画布请求关闭所有菜单 → 父级统一处理。
    SelectionOverlay {
        id: selectionOverlay
        anchors.fill: parent
        z: 60
        onCloseMenusRequested: root.dismissAllMenus()
    }

    // 两阶段图形（椭圆 / 双曲线）第二阶段的焦点手柄层：层级在绘制区（z50）之上、
    // 选择层与工具栏之下；非该阶段时自身 visible=false（不拦截鼠标）。
    FocusHandles {
        id: focusHandles
        objectName: "focusHandlesLayer"
        anchors.fill: parent
        z: 55
    }

    // 课程显示（左上角）；宽度须用 root.width（parent 为 contentItem，窗口隐藏时宽度为 0 导致布局错乱）
    // 层级在笔迹画布之下（笔迹可遮挡课程列表）；未在绘图时（选择工具）课程条仍可正常交互
    Loader {
        id: uiLoader
        objectName: "specialUiLoader"
        source: "LessonsDisplay.qml"
        x: 4
        y: 4
        width: root.width - 8
        height: 54 * lessonsBackend.scaleFactor
        z: 30
        onStatusChanged: {
            if (status === Loader.Ready || status === Loader.Error) {
                root.specialReady()
            }
        }
    }

    // 底部工具栏（仅"交互智能平板"设备可见）：层级高于课程条与右键菜单（rightClickArea z999）、
    // 低于设置蒙层（Dialog Overlay 天然最顶）；工具栏拦截自身区域右键（未来独立右键菜单）。
    Loader {
        id: toolbarLoader
        objectName: "specialToolbarLoader"
        source: "specialmode/SpecialModeToolbar.qml"
        active: settingsBackend.getString("device_type") === "interactive_panel"
        anchors.bottom: parent.bottom
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottomMargin: 28
        z: 1000
        onLoaded: {
            item.windowVisible = Qt.binding(function() { return root.visible })
        }
    }

    // 工具栏擦除全屏请求 → 画布清空并新建会话（保留旧数据文件）
    Connections {
        target: toolbarLoader.item
        function onEraseAllRequested() {
            whiteboardBackend.clearAll()
        }
        function onRequestCloseAllMenus() {
            if (selectionToolbar) selectionToolbar.closeMenus()
        }
        // 数据管理按钮 → 打开数据管理页
        function onDataManagerRequested() {
            root.openDataManager()
        }
    }

    // ---------- 数据管理页（已打开页面 + 历史页面）----------
    // 用户要求：整个手写板上覆盖半透明黑蒙层、居中弹页、右上角 RinUI 图标关闭；
    // **资源只在打开时占用** → 用 Loader 按需加载，关闭时 source 置空（组件连同缩略图一起销毁）；
    // 并在关闭时清掉后端的历史缩略图缓存。
    property bool dataManagerOpen: false
    Loader {
        id: dataManagerLoader
        objectName: "dataManagerLoader"
        anchors.fill: parent
        z: 1010                     // 高于工具栏(z1000)/浮动工具栏(z1001)、低于设置对话框
        source: root.dataManagerOpen ? "specialmode/datamanager/DataManagerOverlay.qml" : ""
        onLoaded: {
            item.closeRequested.connect(function() { root.closeDataManager() })
            // 注意：先做后端动作再关闭（关闭会把弹层卸载掉，若在处理器里同步销毁
            // 正在发信号的项，后面的语句会被中断）
            item.pageRequested.connect(function(index) {
                whiteboardBackend.switchToPage(index)
                root.closeDataManager()
            })
            item.historyRequested.connect(function(file) {
                whiteboardBackend.openHistoryPage(file)
                root.closeDataManager()
            })
        }
    }
    function openDataManager() {
        root.dismissAllMenus()
        root.dataManagerOpen = true
    }
    // 关闭：卸载组件（推迟到下一拍，避免在信号的处理器里销毁发信号者），
    // 并清掉后端的历史缩略图缓存（资源只在打开时占用）
    function closeDataManager() {
        if (!root.dataManagerOpen)
            return
        Qt.callLater(root.unloadDataManager)
    }
    function unloadDataManager() {
        root.dataManagerOpen = false
        whiteboardBackend.clearDataManagerCache()
    }

    // 选中笔划的浮动工具栏（粗细/颜色）：层级高于底部工具栏(z1000)、低于设置蒙层；
    // 位置跟随选中矩形（下方 8px，放不下在上方），仅"选择"工具且有选中时显示。
    SelectionToolbar {
        id: selectionToolbar
        z: 1001
    }

    // 点击二级菜单以外的任意位置自动关闭（仅当工具栏菜单/浮动工具栏二级菜单打开时启用；
    // 低于底部工具栏与浮动工具栏不挡按钮/菜单，只接左键；点画布时先关菜单，再点才绘制）
    MouseArea {
        id: menuDismissArea
        objectName: "menuDismissArea"
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        z: 998
        enabled: (toolbarLoader.item ? toolbarLoader.item.menusOpen : false)
                 || (selectionToolbar ? selectionToolbar.menusOpen : false)
        onClicked: {
            root.dismissAllMenus()
        }
    }

    signal specialReady()

    // 首次启动前先同步一次 RinUI 主题
    Component.onCompleted: {
        root.syncRinuiTheme()
    }

    // 统一关闭所有已打开的菜单：底部工具栏菜单（笔/橡皮）+ 浮动工具栏二级菜单
    function dismissAllMenus() {
        var tbi = toolbarLoader.item
        if (tbi && tbi.closeMenus) tbi.closeMenus()
        if (selectionToolbar && selectionToolbar.closeMenus) selectionToolbar.closeMenus()
    }

    // 插件深浅色 → RinUI 主题同步（whiteboard 浅 / blackboard 深 / normal 随系统主题）
    function syncRinuiTheme() {
        var dark = lessonsBackend.mode === "whiteboard" ? false
            : lessonsBackend.mode === "blackboard" ? true
            : lessonsBackend.isDarkTheme
        Theme.currentTheme = dark ? Theme.dark : Theme.light
    }

    // 模式/系统主题变化时同步（与 LessonsDisplay 自定义 UI 的 effectiveDarkTheme 同帧更新）；
    // 模式切换同时让笔迹画布按新模式重放（已画笔触的黑/白、彩色深浅随之切换显示色）
    Connections {
        target: lessonsBackend
        function onModeChanged() {
            root.syncRinuiTheme()
            whiteboardBackend.setMode(lessonsBackend.mode)
        }
        function onThemeChanged() { root.syncRinuiTheme() }
        // 切到笔/橡皮工具时清除当前选择（蓝色描边/矩形/浮动工具栏一并消失）
        function onActiveToolChanged() {
            if (lessonsBackend.activeTool !== 0) {
                whiteboardBackend.clearSelection()
            }
        }
    }

    // 右键菜单（模仿主程序小组件右键菜单）：特殊模式提供"设置"与"退出xx模式"
    RightClickMenu {
        id: widgetMenu
        onSettingsRequested: settingsDialog.openDialog()
    }

    // 右键打开菜单；已打开时再点空白关闭（左键由 closePolicy 关闭）不再重开
    MouseArea {
        id: rightClickArea
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        propagateComposedEvents: true
        z: 999
        // 记录按下时菜单是否已打开，避免松开后在空白处重开
        property bool pressWhileOpen: false
        onPressed: {
            if (widgetMenu.opened) {
                pressWhileOpen = true
            }
        }
        onClicked: (mouse) => {
            // 右键点击外部时也关闭已打开的二级菜单
            root.dismissAllMenus()
            if (widgetMenu.opened) {
                widgetMenu.close()
            } else if (!pressWhileOpen) {
                widgetMenu.openAt(mouse.x, mouse.y)
            }
            pressWhileOpen = false
        }
    }

    // 设置对话框：模态遮罩在 Overlay 层天然最上层；打开时禁用 mask（否则被裁剪），关闭时恢复
    SettingsDialog {
        id: settingsDialog
    }
}
