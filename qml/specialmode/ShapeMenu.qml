import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 形状菜单（纯 Item，与笔/橡皮/页面菜单同风格：半透明底 + 白色 1px 边框 + 阴影）：
// - 顶部三个分类："平面图形" / "立体形状" / "坐标系"（**"线"页已搬到独立的 LineMenu**，
//   由底部工具栏的"直线"按钮弹出；点任一格即进入对应的绘制状态）
// - 网格布局（列间距 6px；单元格宽 = 内容宽平分后再各减 2px，网格整体居中）：
//     "平面图形"页 **三列**；三个分类取相同的行数（max）→ 切分类时菜单高度稳定。
// - "平面图形"页：等腰三角/直角三角/矩形/五边形/六边形/八边形/星形/圆/扇形/椭圆/
//   双曲线/抛物线 **+ 多边形随心画（最后一排只分两列，它占左列）**
//   （每格用 ShapeIconPreview 画出真实图形），绘制时由起点→终点确定一个横平竖直辅助矩形
//   （不显示），图形内接其中；**五个例外**：圆（起点=圆心、半径 = 起终点距离）；
//   扇形（**两阶段**：起点 = 圆心、拖出第一条半径 → 松手后拖手柄/任意位置定第二条半径，
//   圆心角提示「圆心角 xx°」并吸附 30°/45° 倍数；未完成第二步就切走则生成默认 90° 扇形）；
//   椭圆（起点=中心、终点=一个焦点，松手后进入第二阶段拖焦点手柄定 2a）；
//   直角三角（起点 = 直角顶点，两边横平竖直朝终点象限，拖拽方向接近 30°/45°/60°
//   时吸到那条"特殊角射线"上：45° → 等腰直角三角形）；抛物线（起点 = 顶点、终点 = 焦点）；
//   多边形随心画（**多步**：第一条边松手后逐条接着画 —— 拖手柄或任意位置拖拽，
//   内角提示「xx°」并吸附 30°/45° 倍数、靠近另一端未连线端点时提示「闭合形状」并闭合；
//   中途切工具/改选形状则**直接把缺口闭合**）。
// - "立体形状"页：**三棱柱**（第一个立体图形；后续的立方体/圆柱/圆锥/球…由各自的子 agent
//   编写形状引擎后往 `solidItems` 里加条目，格子尺寸与平面图形页完全一致）；
// - "坐标系"页：**先留空**（结构/切换动画已就位，条目待补上）。
// 当前选中项（lessonsBackend.lineStyle = 图形 id）高亮；未选过则都不高亮
// （**一次绘制结束后后端会清空选择** → 下次打开时无高亮）。
// 切换分类时：选项卡指示条以"弹簧"方式变形（先行端先跑、跟随端慢半拍被拽过去，
// 指示条先被拉长再收回），各页选项横向平移 + 淡入淡出
// （序号大的页在右侧、序号小的在左侧，切换时按方向整体滑动）。
// 点击某项 → lineSelected(id)，由 SpecialModeToolbar 转给 lessonsBackend.setLineStyle(id)。
Item {
    id: root

    signal lineSelected(string style)

    // 深浅色（与工具栏一致：白板=浅色）
    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color dimFg: lightMode ? "#61000000" : "#61FFFFFF"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property color hoverColor: lightMode ? "#0A000000" : "#20FFFFFF"
    readonly property color selectedColor: lightMode ? "#14000000" : "#28FFFFFF"
    readonly property int capsuleRadius: 16

    readonly property int rowSpacing: 2
    readonly property int shapeColCount: 3     // "平面图形"页：三列（**最后一排只两列**，见 shapeTail*）
    readonly property int cellGap: 6           // 列间距
    readonly property int cellH: 54
    // 顶部选项卡区：选项卡（胶囊）高 chipH；
    // 选中时**改背景色**，并在选项卡**底部**画一条圆角指示条（高 chipBarH、圆角 = 高度/2、
    // 宽 = 选项卡宽 * 0.6 − 10、水平居中、底边与选项卡底边对齐）；
    // 指示条是三个选项卡**共用**的一条 → 切换分类时平移到目标选项卡下方并做宽度过渡。
    readonly property int chipH: 32
    readonly property int chipBarH: 3
    readonly property int chipBarRadius: 2      // ≥ 高/2 → Qt 自动夹成胶囊形
    // 指示条"弹簧"动画：两端点各自跑——先行端（向右移动时是右端、向左时是左端）起步快、
    // 很快到位；跟随端起步慢（像被拽着走）→ 中段加速 → 稳稳落到目标。两端速度差让
    // 指示条先被拉长、再收回目标宽度。
    readonly property int springLeadMs: 250    // 先行端：OutCubic（起步干脆、很快到位）
    readonly property int springTrailMs: 250    // 跟随端：InOutQuad（慢起步被拽 → 中段快 → 稳稳落点）
    readonly property int slideMs: 300         // 选项区整页平移/渐变时长（行程一个内容区宽）
    readonly property int headGap: 16          // 选项卡区 → 下方选项区的间距
    // 单元格宽度：内容宽平分后再**各减 2px**（"稍微减小一点点"），
    // 剩下的余量均分在两侧 → 网格整体居中。
    readonly property int contentW: root.width - 28
    readonly property int cellW: Math.floor((root.contentW - root.cellGap * (root.colCount - 1))
                                            / root.colCount) - 2
    readonly property int shapeCellW: Math.floor((root.contentW - root.cellGap * (root.shapeColCount - 1))
                                                 / root.shapeColCount) - 2
    // 图形页的**最后一排只分两列**（格子更宽），里面只有"多边形随心画"（位于左列）：
    // 前面 (n-1) 项仍按三列排，最后一项单独一排、两列平分（宽度对齐三列网格的总宽）。
    readonly property var shapeTailItems: root.shapeItems.length > 0
                                          ? root.shapeItems.slice(root.shapeItems.length - 1) : []
    readonly property var shapeMainItems: root.shapeItems.slice(0, Math.max(0, root.shapeItems.length - 1))
    readonly property int shapeTailCols: 2
    readonly property int shapeTailW: root.shapeColCount * root.shapeCellW
                                      + (root.shapeColCount - 1) * root.cellGap
    readonly property int shapeTailCellW: Math.floor((root.shapeTailW - root.cellGap) / root.shapeTailCols) - 2
    // 行数按条目数动态算（平面图形页 = 三列的行数 + 最后一排）；三个分类取较大者 →
    // 切分类时菜单高度稳定（"立体形状"/"坐标系"暂时是空页，高度仍与平面图形页一致）
    readonly property int shapeMainRows: Math.max(1, Math.ceil(root.shapeMainItems.length / root.shapeColCount))
    readonly property int shapeRows: root.shapeMainRows + (root.shapeTailItems.length > 0 ? 1 : 0)
    // "立体形状"页：**同样是三列**，格子尺寸/间距与"平面图形"页完全一致（用户要求）
    readonly property int solidRows: Math.max(1, Math.ceil(root.solidItems.length / root.shapeColCount))
    // "坐标系"页：**每行只分两列**（用户要求）→ 格子更宽（宽度对齐三列网格的总宽）
    readonly property int axisColCount: 2
    readonly property int axisCellW: Math.floor((root.contentW - root.cellGap) / root.axisColCount) - 2
    readonly property int axisRows: Math.max(1, Math.ceil(root.axisItems.length / root.axisColCount))
    readonly property int rows: Math.max(root.shapeRows, root.solidRows, root.axisRows)
    // 0=平面图形 1=立体形状 2=坐标系（坐标系页：平面直角坐标系 / 空间直角坐标系）
    property int category: 0
    readonly property int categoryCount: 3
    readonly property var shapeItems: lessonsBackend.shapeItems
    // 立体图形（三棱柱…）：每个图形的形状引擎在后端单独注册（见 main.py `_register_solid`）
    readonly property var solidItems: lessonsBackend.solidItems
    // 坐标系（平面/空间直角坐标系）：轴就是带箭头的直线（见 main.py `_AXIS_MENU_KINDS`）
    readonly property var axisItems: lessonsBackend.axisItems

    // 预览用的线宽：跟随笔的粗细，但至少 3px（细线在菜单里看不清）
    readonly property real previewW: Math.max(3, lessonsBackend.penWidth)
    // 预览颜色：跟随笔的颜色（逻辑色名 → 当前模式显示色）
    readonly property color previewColor: lessonsBackend.penColor === "mono"
                                           ? fg : root.colorFor(lessonsBackend.penColor)

    // 内容区高（按行数算出）与菜单总高：**直接用公式算**而不是依赖 Column 的
    // implicitHeight——后者要等布局抛光才就绪，而打开菜单时立刻要用 height 做定位。
    readonly property int contentH: root.rows * root.cellH + (root.rows - 1) * root.rowSpacing
    // 图形页前几排（三列）的总高 → 最后一排（两列）的 y（公式直算，避免 positioner 首帧高度为 0 而跳位）
    readonly property int shapeMainH: root.shapeMainRows * root.cellH
                                      + (root.shapeMainRows - 1) * root.rowSpacing
    width: 236
    // 14(上) + 选项卡区(高 chipH) + headGap + contentH + 14(下)
    height: root.contentH + 14 + root.chipH + root.headGap + 14

    // 逻辑颜色名 → 当前模式显示 hex（与 PenMenu.colorFor 一致）
    function colorFor(logical) {
        if (logical === "mono") return root.lightMode ? "#000000" : "#FFFFFF"
        var lightHex = {"red":"#C62828","blue":"#1565C0","green":"#2E7D32",
                        "orange":"#EF6C00","yellow":"#F9A825","cyan":"#00838F","purple":"#6A1B9A"}
        var darkHex = {"red":"#EF5350","blue":"#42A5F5","green":"#66BB6A",
                       "orange":"#FFA726","yellow":"#FFEE58","cyan":"#4DD0E1","purple":"#AB47BC"}
        return root.lightMode ? (lightHex[logical] || "#000000") : (darkHex[logical] || "#FFFFFF")
    }

    // 线型的预览已搬到独立菜单：见 LineMenu.qml（底部工具栏"直线"按钮弹出）。
    // 图形预览：ShapeIconPreview.qml（同一套顶点公式，与 Python 侧 _figure_points 一致）。

    // 阴影 + 背景（与工具栏胶囊一致）
    DropShadow {
        anchors.fill: parent
        source: menuBgRect
        radius: 20
        samples: 40
        color: "#22000000"
        transparentBorder: true
    }
    Rectangle {
        id: menuBgRect
        anchors.fill: parent
        radius: root.capsuleRadius
        color: root.capsuleColor
        border.width: 1
        border.color: root.capsuleBorder
    }

    // 分类切换按钮："平面图形" / "立体图形" / "坐标系"——选中时**改背景色**
    //（未悬停也能看出选中），指示条不在自己内部画：见下方 chipArea 里共用的 chipIndicator。
    component CategoryChip: Item {
        id: chip
        objectName: "categoryChip_" + chip.label
        property string label: ""
        property int index: 0
        property bool active: false
        width: chipText.implicitWidth + 22
        height: root.chipH
        Rectangle {
            id: chipBg
            objectName: "categoryChipBg_" + chip.label
            anchors.fill: parent
            radius: height / 2
            // 选中 → 底色；未选但悬停 → 更淡的悬停色
            color: chip.active ? root.selectedColor
                 : (chipMa.containsMouse ? root.hoverColor : "transparent")
            Behavior on color { ColorAnimation { duration: 120 } }
            Text {
                id: chipText
                anchors.centerIn: parent
                text: chip.label
                // 选中/未选中同透明度：统一用不透明度更高的 fg（alpha 0xE6）
                color: root.fg
                font.family: Qt.application.font.family
                font.pixelSize: 12
                font.bold: chip.active
            }
            MouseArea {
                id: chipMa
                anchors.fill: parent
                hoverEnabled: true
                onClicked: chip.active ? undefined : (root.category = chip.index)
            }
        }
    }

    // 图形格子：上=图形轮廓预览（Canvas 按同一套顶点公式自绘），下=名称；可点选
    component ShapeCell: Item {
        id: scell
        property string shapeId: ""
        property string shapeName: ""
        // 属于哪个分类页（0=平面图形 / 1=立体形状）：非当前页不接收点击
        property int pageIndex: 0
        // 格子宽：三列网格用 shapeCellW（≈63）；**最后一排两列**用更宽的 shapeTailCellW
        property int cellWidth: root.shapeCellW
        width: scell.cellWidth
        height: root.cellH
        Rectangle {
            anchors.fill: parent
            radius: 10
            color: scellMa.containsMouse ? root.hoverColor
                 : (lessonsBackend.lineStyle === scell.shapeId ? root.selectedColor : "transparent")
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        ShapeIconPreview {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 7
            width: 26
            height: 24
            kind: scell.shapeId
            // 立体图形小图**固定用正等测**：用户的“测画方式”只影响画到画布上的样子，
            // 菜单小图不跟着变（用户要求：无论选了哪种测画法，圆柱/圆锥小图都用正等测）
            // （其余立体图形的小图分支本来就固定斜二测，不受这个属性影响）
            projMode: "iso"
            lineWidth: 2
            // 与"线"页每格的线条同色/同透明度（previewColor）：不选时不比线条淡
            lineColor: root.previewColor
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            text: scell.shapeName
            color: lessonsBackend.lineStyle === scell.shapeId ? root.fg : root.dimFg
            font.family: Qt.application.font.family
            font.pixelSize: 12
            font.bold: lessonsBackend.lineStyle === scell.shapeId
        }
        MouseArea {
            id: scellMa
            anchors.fill: parent
            hoverEnabled: true
            // 非当前页（正在滑出/淡出）不接收点击
            enabled: root.category === scell.pageIndex
            onClicked: root.lineSelected(scell.shapeId)
        }
    }

    Column {
        id: col
        x: 14
        y: 14
        width: parent.width - 28
        spacing: root.headGap

        // 选项卡区（Row + 共用指示条一起放在一个 Item 里，Column 只看到"一项"）
        Item {
            id: chipArea
            objectName: "categoryChipArea"
            width: chipRow.width
            height: chipRow.height
            // 创建阶段（字体度量/初始赋值）不播动画；组件完成后再启用
            property bool animReady: false
            Component.onCompleted: animReady = true

            Row {
                id: chipRow
                spacing: 3
                CategoryChip { id: chipShape; label: "平面图形"; index: 0; active: root.category === 0 }
                CategoryChip { id: chipSolid; label: "立体图形"; index: 1; active: root.category === 1 }
                CategoryChip { id: chipAxis; label: "坐标系"; index: 2; active: root.category === 2 }
                // 三个选项卡的目标（按 index 取，供指示条定位）
                readonly property var chips: [chipShape, chipSolid, chipAxis]
            }

            // 三个选项卡**共用**的选中指示条：左右端点**各自**跑，做出弹簧感。
            //  - 先行端（往右边的分类是右端、往左边的是左端）：OutCubic，起步干脆、很快到位；
            //  - 跟随端：InOutCubic，起步慢（像被拽着走）→ 中段加速 → 稳稳落到目标；
            // 两端速度差 → 指示条先被拉长，再收回目标宽度（= 选项卡宽*0.6-10、居中、贴底）。
            // 注意：**不能用 Behavior + 按方向绑定 easing/duration** —— 实测参数的绑定
            // 只在第一次动画时求值（之后不再更新），反向切换会沿用上一次的角色把指示条压反。
            // 所以这里用 4 个显式 NumberAnimation，由 applySpring() 按方向挑选并启动。
            Rectangle {
                id: chipIndicator
                objectName: "categoryIndicator"
                readonly property var target: chipRow.chips[Math.max(0, Math.min(root.categoryCount - 1,
                                                                                root.category))]
                // 两端内缩量：宽度 = 选项卡宽 - 2*inset = 选项卡宽*0.6 - 10
                readonly property real inset: target ? (target.width * 0.2 + 5) : 0
                readonly property real targetLeft: target ? (target.x + inset) : 0
                readonly property real targetRight: target ? (target.x + target.width - inset) : 0
                property real leftEdge: 0
                property real rightEdge: 0
                x: leftEdge
                y: root.chipH - root.chipBarH
                width: Math.max(0, rightEdge - leftEdge)
                height: root.chipBarH
                radius: root.chipBarRadius
                color: root.fg

                NumberAnimation {
                    id: aLeftLead
                    target: chipIndicator; property: "leftEdge"
                    duration: root.springLeadMs; easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    id: aLeftTrail
                    target: chipIndicator; property: "leftEdge"
                    duration: root.springTrailMs; easing.type: Easing.InOutQuad
                }
                NumberAnimation {
                    id: aRightLead
                    target: chipIndicator; property: "rightEdge"
                    duration: root.springLeadMs; easing.type: Easing.OutCubic
                }
                NumberAnimation {
                    id: aRightTrail
                    target: chipIndicator; property: "rightEdge"
                    duration: root.springTrailMs; easing.type: Easing.InOutQuad
                }

                function stopSpring() {
                    aLeftLead.stop()
                    aLeftTrail.stop()
                    aRightLead.stop()
                    aRightTrail.stop()
                }
                // 直接落到目标（初始化 / 菜单重新打开时用，不播动画）
                function snapToTarget() {
                    stopSpring()
                    leftEdge = targetLeft
                    rightEdge = targetRight
                }
                // 弹簧过渡：往右（新分类序号更大）右端先行；往左左端先行
                function applySpring(fromCat, toCat) {
                    stopSpring()
                    var t = chipRow.chips[Math.max(0, Math.min(root.categoryCount - 1, toCat))]
                    if (!t) return
                    var ins = t.width * 0.2 + 5
                    var tl = t.x + ins
                    var tr = t.x + t.width - ins
                    var l0 = leftEdge
                    var r0 = rightEdge
                    if (toCat > fromCat) {         // 向右：右端先冲出去，左端被拽过去
                        aRightLead.from = r0; aRightLead.to = tr; aRightLead.start()
                        aLeftTrail.from = l0; aLeftTrail.to = tl; aLeftTrail.start()
                    } else if (toCat < fromCat) {  // 向左：左端先冲出去，右端被拽过去
                        aLeftLead.from = l0; aLeftLead.to = tl; aLeftLead.start()
                        aRightTrail.from = r0; aRightTrail.to = tr; aRightTrail.start()
                    } else {
                        snapToTarget()
                    }
                }
                Component.onCompleted: snapToTarget()
                // 目标选项卡变了 → 按"从上一个分类到新分类"的方向播弹簧
                property int lastCat: 0
                onTargetChanged: {
                    if (chipArea.animReady)
                        applySpring(lastCat, root.category)
                    else
                        snapToTarget()
                    lastCat = root.category
                }
            }
        }

        // 各页内容高度一致（rows 行）→ 切分类时菜单高度稳定。
        // 切换分类时各页一起做**横向平移 + 渐变**：序号比当前页大的停在右侧、小的停在左侧，
        // 滑出画面的页同时淡出、滑入的页淡入（与旧版两页时的观感/参数完全一致）。
        // 曲线用基础的非线性缓动 OutQuad（起步干脆、尾部缓收），与选项卡指示条各自独立。
        Item {
            id: contentArea
            objectName: "categoryContentArea"
            width: parent.width
            height: root.contentH
            clip: true        // 滑出的一页裁在内容区内，不会溢出菜单
            readonly property real slideW: width   // 平移距离 = 内容区宽（足够滑出画面）
            property bool animReady: false         // 创建阶段不播动画（与指示条同规则）
            Component.onCompleted: animReady = true

            // "平面图形"页：上面几排三列 + **最后一排只分两列**（里面只有"多边形随心画"，
            // 位于左列）。两页（Grid + 最后一排）一起放进本 Item → 整页平移/渐变时
            // 两排同步滑动（不会一前一后）。
            Item {
                id: shapePage
                objectName: "shapePage"
                width: parent.width
                height: root.contentH
                // 本页为当前页 → 居中；否则按序号整体滑出画（序号大 → 停在右侧等滑入）
                x: (parent.width - width) / 2 + (0 - root.category) * parent.slideW
                opacity: root.category === 0 ? 1 : 0
                visible: opacity > 0.01
                Behavior on x {
                    enabled: contentArea.animReady
                    NumberAnimation { duration: root.slideMs; easing.type: Easing.OutQuad }
                }
                Behavior on opacity {
                    enabled: contentArea.animReady
                    NumberAnimation { duration: root.slideMs; easing.type: Easing.OutQuad }
                }

                Grid {
                    id: shapeGrid
                    objectName: "shapeGrid"
                    columns: root.shapeColCount
                    columnSpacing: root.cellGap
                    rowSpacing: root.rowSpacing
                    x: (parent.width - width) / 2
                    Repeater {
                        model: root.shapeMainItems
                        delegate: ShapeCell {
                            required property var modelData
                            shapeId: modelData.id
                            shapeName: modelData.name
                        }
                    }
                }

                // 最后一排：只分两列（格子宽 = 上排三列的总宽平分），左边缘与上排对齐
                Grid {
                    id: shapeTailGrid
                    objectName: "shapeTailGrid"
                    columns: root.shapeTailCols
                    columnSpacing: root.cellGap
                    rowSpacing: root.rowSpacing
                    x: shapeGrid.x
                    y: root.shapeMainH + root.rowSpacing
                    Repeater {
                        model: root.shapeTailItems
                        delegate: ShapeCell {
                            required property var modelData
                            shapeId: modelData.id
                            shapeName: modelData.name
                            cellWidth: root.shapeTailCellW
                        }
                    }
                }
            }

            // "立体形状"页（序号 1）：**三列**，格子尺寸/行距与"平面图形"页一致。
            // 每个立体图形（三棱柱/…）的图标由 ShapeIconPreview 用同一套斜二测公式自绘；
            // 绘制引擎在后端（`_register_solid`），新增立体图形只往 `solidItems` 里加条目。
            Item {
                id: solidPage
                objectName: "solidPage"
                width: parent.width
                height: root.contentH
                x: (parent.width - width) / 2 + (1 - root.category) * parent.slideW
                opacity: root.category === 1 ? 1 : 0
                visible: opacity > 0.01
                Behavior on x {
                    enabled: contentArea.animReady
                    NumberAnimation { duration: root.slideMs; easing.type: Easing.OutQuad }
                }
                Behavior on opacity {
                    enabled: contentArea.animReady
                    NumberAnimation { duration: root.slideMs; easing.type: Easing.OutQuad }
                }

                Grid {
                    id: solidGrid
                    objectName: "solidGrid"
                    columns: root.shapeColCount
                    columnSpacing: root.cellGap
                    rowSpacing: root.rowSpacing
                    x: (parent.width - width) / 2
                    Repeater {
                        model: root.solidItems
                        delegate: ShapeCell {
                            required property var modelData
                            shapeId: modelData.id
                            shapeName: modelData.name
                            pageIndex: 1
                        }
                    }
                }
            }

            // "坐标系"页（序号 2）：**每行两列**（用户要求），格子宽 = 内容宽平分两列。
            // 条目：平面直角坐标系 / 空间直角坐标系（图标由 ShapeIconPreview 自绘：
            // 几条相交的带箭头直线，箭头样式与直线菜单一致）。
            Item {
                id: axisPage
                objectName: "axisPage"
                width: parent.width
                height: root.contentH
                x: (parent.width - width) / 2 + (2 - root.category) * parent.slideW
                opacity: root.category === 2 ? 1 : 0
                visible: opacity > 0.01
                Behavior on x {
                    enabled: contentArea.animReady
                    NumberAnimation { duration: root.slideMs; easing.type: Easing.OutQuad }
                }
                Behavior on opacity {
                    enabled: contentArea.animReady
                    NumberAnimation { duration: root.slideMs; easing.type: Easing.OutQuad }
                }

                Grid {
                    id: axisGrid
                    objectName: "axisGrid"
                    columns: root.axisColCount
                    columnSpacing: root.cellGap
                    rowSpacing: root.rowSpacing
                    x: (parent.width - width) / 2
                    Repeater {
                        model: root.axisItems
                        delegate: ShapeCell {
                            required property var modelData
                            shapeId: modelData.id
                            shapeName: modelData.name
                            cellWidth: root.axisCellW
                            pageIndex: 2
                        }
                    }
                }
            }
        }
    }
}
