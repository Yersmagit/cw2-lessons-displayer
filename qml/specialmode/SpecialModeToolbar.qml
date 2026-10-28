import QtQuick 2.15
import QtQuick.Window 2.15
import Qt5Compat.GraphicalEffects

// 特殊模式底部工具栏（仅"交互智能平板"设备可见）：左=退出/切换模式，中=选择/笔/橡皮分段选择器，
// 右=上一页/下一页。除图标（RinUI Icon）外全部自绘；颜色随模式反色（白板浅色/熄屏深色）且有过渡动画
// （模式切换直接平滑变样式）；胶囊带白色 1px 边框与阴影；打开/关闭特殊模式时透明度渐入渐出。
Item {
    id: root

    // 根尺寸跟随三个胶囊的实际布局（否则容器 0 尺寸导致内容不可见）
    width: capsulesRow.width
    height: root.capsuleH

    // 橡皮擦除全屏请求（由 SpecialModeWindow 连接画布 clearAll）
    signal eraseAllRequested()
    // 请求关闭所有菜单（含浮动工具栏二级菜单），由 SpecialModeWindow 统一处理
    signal requestCloseAllMenus()
    // 打开"数据管理"页（由 SpecialModeWindow 加载弹层）
    signal dataManagerRequested()

    // 二级菜单显示在相应按钮上方，菜单底部距工具栏顶部 8px（水平居中于按钮）。
    // 菜单是工具栏子对象，y 为负表示在工具栏上方空间（窗口内）。
    function positionMenuAbove(menu, anchorItem) {
        menu.visible = true
        var tl = anchorItem.mapToItem(root, 0, 0)
        menu.x = tl.x + anchorItem.width / 2 - menu.width / 2
        menu.y = -menu.height - 8
        if (menu.x < 0) menu.x = 0
        // 不超出窗口右边界（页面列表菜单较宽；菜单高度已由 PageListMenu 限制在屏幕内）
        var win = root.Window
        if (win && menu.x + menu.width > win.width) {
            menu.x = Math.max(0, win.width - menu.width)
        }
    }
    function closeMenus() {
        penMenu.visible = false
        eraserMenu.visible = false
        pageListMenu.visible = false
        shapeMenu.visible = false
        lineMenu.visible = false
        solidProjMenu.visible = false
    }
    // 当前选中的线型属于"线型"还是"图形"（决定两颗选中指示器哪一颗亮）
    function isLineStyle(id) {
        if (!id) return false
        var a = lessonsBackend.lineStyleItems
        for (var i = 0; i < a.length; i++) if (a[i].id === id) return true
        return false
    }
    function isShapeStyle(id) {
        if (!id) return false
        var a = lessonsBackend.shapeItems
        for (var i = 0; i < a.length; i++) if (a[i].id === id) return true
        // 立体图形（三棱柱…）也走"形状"这一套：选中它们时形状指示器同样点亮
        var b = lessonsBackend.solidItems
        if (b) for (var j = 0; j < b.length; j++) if (b[j].id === id) return true
        return false
    }
    // 是否有菜单打开（供 SpecialModeWindow 的菜单外点击关闭层判断）
    // ⚠️ **故意不算测画方式菜单**（solidProjMenu）：它选定后不自动关，而是等用户开始画底面。
    // 若把它算进来，那次按下会被「菜单外点击关闭层」吃掉（只关菜单不画）→ 用户得点两下。
    // 不计入则那次按下直接落到绘制区：先 `closeMenus()`（菜单立刻收起）再 `beginLine`，
    // 正是用户要的"一旦开始绘制底面就把菜单关掉，并按菜单上的选择画底面"。
    readonly property bool menusOpen: penMenu.visible || eraserMenu.visible
                                      || pageListMenu.visible || shapeMenu.visible
                                      || lineMenu.visible

    // 窗口可见性（由 SpecialModeWindow 绑定）：true→淡入，false→渐隐
    property bool windowVisible: false

    // 设备类型非交互智能平板 → 不显示
    visible: settingsBackend.deviceType === "interactive_panel"
    opacity: windowVisible ? 1 : 0
    Behavior on opacity {
        NumberAnimation { duration: 300; easing.type: Easing.OutCubic }
    }

    // 尺寸常量
    readonly property int btnSize: 56
    readonly property int btnIconSize: 24
    readonly property int btnFontSize: 12
    readonly property int capsuleH: 64
    readonly property int capsuleRadius: capsuleH / 2
    readonly property int capsulePad: 4

    // 配色（随模式反色；选中/悬停浅色模式不透明度更低）
    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fgColor: lightMode ? "#E6000000" : "#E6FFFFFF"
    // 胶囊背景：统一半透明灰（alpha 5%），深浅色一致
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    // 按钮悬停背景：浅色 8% / 深色 20%
    readonly property color hoverColor: lightMode ? "#0A000000" : "#20FFFFFF"
    readonly property color pressedColor: lightMode ? "#10000000" : "#28FFFFFF"
    // 分段选中指示器：浅色 12% / 深色 25%
    readonly property color selectedColor: lightMode ? "#10000000" : "#28FFFFFF"
    readonly property color dividerColor: lightMode ? "#30000000" : "#33FFFFFF"  // 中胶囊竖线分割色

    // 工具栏区域右键拦截（预留独立右键菜单）；同时吞掉左键避免漏到画布误绘；
    // 点击工具栏空白处（按钮之间）也关闭已打开的二级菜单（含浮动工具栏二级菜单）
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        z: -1
        onClicked: {
            root.closeMenus()
            root.requestCloseAllMenus()
        }
    }

    // 三个胶囊横向分布
    Row {
        id: capsulesRow
        anchors.centerIn: parent
        spacing: 16
        // 左胶囊：退出 / 切换模式（白色 1px 边框 + 阴影）
        Item {
            width: leftRow.width + root.capsulePad * 2
            height: root.capsuleH
            DropShadow {
                anchors.fill: parent
                source: leftCapsule
                radius: 20
                samples: 40
                color: "#22000000"
                transparentBorder: true
            }
            Rectangle {
                id: leftCapsule
                anchors.fill: parent
                radius: root.capsuleRadius
                color: root.capsuleColor
                border.width: 1
                border.color: "#33FFFFFF"
                Behavior on color { ColorAnimation { duration: 150 } }

                Row {
                    id: leftRow
                    anchors.centerIn: parent
                    spacing: 2
                    CircleToolButton {
                        label: "退出"
                        iconName: "ic_fluent_arrow_exit_20_regular"
                        fg: root.fgColor
                        bgHover: root.hoverColor
                        bgPressed: root.pressedColor
                        btnSize: root.btnSize
                        iconSize: root.btnIconSize
                        fontSize: root.btnFontSize
                        onClicked: {
                            root.closeMenus()
                            lessonsBackend.exitSpecialMode()
                        }
                    }
                    CircleToolButton {
                        // 切换按钮：文字显示将切换到的实际模式，图标用太阳/月亮
                        // （白板→黑板月亮、黑板→白板太阳）；工具栏仅平板显示，故直接称"黑板"/"白板"
                        objectName: "modeBtn"
                        label: lessonsBackend.mode === "whiteboard" ? "黑板" : "白板"
                        iconName: lessonsBackend.mode === "whiteboard"
                                  ? "ic_fluent_weather_moon_20_regular"
                                  : "ic_fluent_weather_sunny_20_regular"
                        fg: root.fgColor
                        bgHover: root.hoverColor
                        bgPressed: root.pressedColor
                        btnSize: root.btnSize
                        iconSize: root.btnIconSize
                        fontSize: root.btnFontSize
                        onClicked: {
                            root.closeMenus()
                            if (lessonsBackend.mode === "whiteboard")
                                lessonsBackend.enterBlackboard()
                            else
                                lessonsBackend.enterWhiteboard()
                        }
                    }
                    // 文件管理（在"退出"/"白板-黑板"按钮的**右侧**）：
                    // 打开文件管理页（最近页面 / 保存 / 另存 / 导出图片，见 qml/specialmode/datamanager/）
                    CircleToolButton {
                        objectName: "dataManagerBtn"
                        label: "文件管理"
                        iconName: "ic_fluent_text_bullet_list_20_regular"
                        fg: root.fgColor
                        bgHover: root.hoverColor
                        bgPressed: root.pressedColor
                        btnSize: root.btnSize
                        iconSize: root.btnIconSize
                        fontSize: root.btnFontSize
                        onClicked: {
                            root.closeMenus()
                            root.dataManagerRequested()
                        }
                    }
                }
            }
        }

        // 中胶囊：分段选择器（选择/笔/橡皮）+ 独立"撤销"按钮（竖线分割，互不影响）
        Item {
            width: middleRow.width + root.capsulePad * 2
            height: root.capsuleH
            DropShadow {
                anchors.fill: parent
                source: segCapsule
                radius: 20
                samples: 40
                color: "#22000000"
                transparentBorder: true
            }
            Rectangle {
                id: segCapsule
                objectName: "segCapsule"
                property int segIndex: 0  // 0=选择 1=笔 2=橡皮
                anchors.fill: parent
                radius: root.capsuleRadius
                color: root.capsuleColor
                border.width: 1
                border.color: "#33FFFFFF"
                Behavior on color { ColorAnimation { duration: 150 } }

                Row {
                    id: middleRow
                    anchors.centerIn: parent
                    spacing: 0

                    // 分段控制器区域（含选中指示器）
                    Item {
                        id: segArea
                        width: segRow.width
                        height: root.btnSize

                        // 选中指示器：始终存在的半透明圆表示当前选中项，切换时平移到对应项（动画）；
                        // 形状工具激活时**原地渐隐**（形状胶囊有自己的指示器，不平移过渡）
                        Rectangle {
                            id: segIndicator
                            objectName: "segIndicator"
                            width: root.btnSize
                            height: root.btnSize
                            radius: width / 2
                            color: root.selectedColor
                            opacity: lessonsBackend.activeTool === 3 ? 0 : 1
                            Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            Behavior on color { ColorAnimation { duration: 150 } }
                            x: segRow.x + (segCapsule.segIndex === 0 ? segSelectBtn.x
                                              : segCapsule.segIndex === 1 ? segPenBtn.x : segEraserBtn.x)
                            Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                        }

                        Row {
                            id: segRow
                            spacing: 2
                            CircleToolButton {
                                id: segSelectBtn
                                objectName: "segSelectBtn"
                                label: "选择"
                                iconName: "ic_fluent_cursor_20_regular"
                                hoverFade: true
                                fg: root.fgColor
                                bgHover: root.hoverColor
                                bgPressed: root.pressedColor
                                btnSize: root.btnSize
                                iconSize: root.btnIconSize
                                fontSize: root.btnFontSize
                                onClicked: {
                                    root.closeMenus()
                                    segCapsule.segIndex = 0
                                    lessonsBackend.setActiveTool(0)
                                    root.requestCloseAllMenus()
                                }
                            }
                            CircleToolButton {
                                id: segPenBtn
                                objectName: "segPenBtn"
                                label: "笔"
                                iconName: "ic_fluent_pen_20_regular"
                                hoverFade: true
                                acceptRightClick: true
                                fg: root.fgColor
                                bgHover: root.hoverColor
                                bgPressed: root.pressedColor
                                btnSize: root.btnSize
                                iconSize: root.btnIconSize
                                fontSize: root.btnFontSize
                                // 已选中笔 → 显示展开指示器（提示再点展开）；笔菜单打开 → 指示器旋转 180°。
                                // ⚠️ 还要跟 `activeTool` 对齐：形状工具（activeTool=3）激活时笔并没被选中
                                // （segIndex 为了"画完回退"仍保留旧值）→ 小箭头必须跟着隐藏（用户报的问题）。
                                showExpandIndicator: (segCapsule.segIndex === 1
                                                      && lessonsBackend.activeTool === 1)
                                                     || penMenu.visible
                                expandIndicatorRotated: penMenu.visible
                                // 已选中笔时再点 → 弹笔菜单（再点切换关闭）；右键 → 弹笔菜单。
                                // ⚠️ 判断必须同时看 `activeTool`：形状工具（activeTool=3）激活期间
                                // `segIndex` 仍留着旧值（为了画完回退），否则“形状画到一半再点笔”
                                // 会弹菜单而不是直接选中笔（用户要求）。
                                onClicked: {
                                    if (segCapsule.segIndex === 1
                                            && lessonsBackend.activeTool === 1) {
                                        if (penMenu.visible) root.closeMenus()
                                        else root.positionMenuAbove(penMenu, segPenBtn)
                                    } else {
                                        segCapsule.segIndex = 1
                                        lessonsBackend.setActiveTool(1)
                                        root.closeMenus()
                                    }
                                }
                                onRightClicked: {
                                    if (penMenu.visible) root.closeMenus()
                                    else root.positionMenuAbove(penMenu, segPenBtn)
                                }
                            }
                            CircleToolButton {
                                id: segEraserBtn
                                objectName: "segEraserBtn"
                                label: "橡皮"
                                iconName: "ic_fluent_eraser_20_regular"
                                hoverFade: true
                                acceptRightClick: true
                                fg: root.fgColor
                                bgHover: root.hoverColor
                                bgPressed: root.pressedColor
                                btnSize: root.btnSize
                                iconSize: root.btnIconSize
                                fontSize: root.btnFontSize
                                // 已选中橡皮 → 显示展开指示器（提示再点展开）；擦除菜单打开 → 指示器旋转 180°。
                                // 同样要跟 `activeTool` 对齐（形状工具激活时橡皮没被选中 → 箭头隐藏）
                                showExpandIndicator: (segCapsule.segIndex === 2
                                                      && lessonsBackend.activeTool === 2)
                                                     || eraserMenu.visible
                                expandIndicatorRotated: eraserMenu.visible
                                // 已选中橡皮时再点 → 弹擦除全屏菜单（再点切换关闭）；右键 → 弹擦除全屏菜单。
                                // 同样要跟 `activeTool` 对齐（形状工具激活时再点橡皮要**直接选中橡皮**）
                                onClicked: {
                                    if (segCapsule.segIndex === 2
                                            && lessonsBackend.activeTool === 2) {
                                        if (eraserMenu.visible) root.closeMenus()
                                        else root.positionMenuAbove(eraserMenu, segEraserBtn)
                                    } else {
                                        segCapsule.segIndex = 2
                                        lessonsBackend.setActiveTool(2)
                                        root.closeMenus()
                                    }
                                }
                                onRightClicked: {
                                    if (eraserMenu.visible) root.closeMenus()
                                    else root.positionMenuAbove(eraserMenu, segEraserBtn)
                                }
                            }
                        }
                    }

                    // 竖线左侧间距
                    Item { width: 4; height: 1 }

                    // 竖线分割（分段控制器与撤销之间）
                    Rectangle {
                        width: 1
                        height: root.capsuleH - 24
                        color: root.dividerColor
                        Behavior on color { ColorAnimation { duration: 150 } }
                        anchors.verticalCenter: parent.verticalCenter
                    }

                    // 竖线右侧间距
                    Item { width: 4; height: 1 }

                    // 撤销：独立按钮，与分段控制器互不影响；悬停效果与其他按钮一致（圆背景）；
                    // 无可撤销操作时半透明显示；点击撤销上一步（新增笔划/清屏/移动/缩放/换色/换粗细）
                    CircleToolButton {
                        objectName: "undoBtn"
                        label: "撤销"
                        iconName: "ic_fluent_arrow_undo_20_regular"
                        fg: root.fgColor
                        bgHover: root.hoverColor
                        bgPressed: root.pressedColor
                        btnSize: root.btnSize
                        iconSize: root.btnIconSize
                        fontSize: root.btnFontSize
                        opacity: whiteboardBackend.canUndo ? 1.0 : 0.35
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                        onClicked: {
                            root.closeMenus()
                            whiteboardBackend.undo()
                        }
                    }
                }
            }
        }

        // 形状胶囊（位于中胶囊与右胶囊之间）：**直线**菜单入口 + **形状**菜单入口。
        // 两颗按钮各有**独立的**选中指示器（不参与中胶囊的平移）：选了线型 → 直线指示器原地渐显；
        // 选了平面/立体图形 → 形状指示器原地渐显（同时中胶囊的选择/笔/橡皮指示器原地渐隐）；
        // 画完一条后自动回退、指示器再各自渐回。
        Item {
            width: shapeRow.width + root.capsulePad * 2
            height: root.capsuleH
            DropShadow {
                anchors.fill: parent
                source: shapeCapsule
                radius: 20
                samples: 40
                color: "#22000000"
                transparentBorder: true
            }
            Rectangle {
                id: shapeCapsule
                anchors.fill: parent
                radius: root.capsuleRadius
                color: root.capsuleColor
                border.width: 1
                border.color: "#33FFFFFF"
                Behavior on color { ColorAnimation { duration: 150 } }

                Row {
                    id: shapeRow
                    anchors.centerIn: parent
                    spacing: 2
                    // 直线按钮（形状按钮左侧）：弹出线菜单（原来的"形状 > 线"页）
                    Item {
                        width: root.btnSize
                        height: root.btnSize
                        // 直线选中指示器：形状工具激活 **且当前选中的是线型** 时原地渐显
                        Rectangle {
                            objectName: "lineIndicator"
                            anchors.fill: parent
                            radius: width / 2
                            color: root.selectedColor
                            opacity: (lessonsBackend.activeTool === 3
                                      && root.isLineStyle(lessonsBackend.lineStyle)) ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        CircleToolButton {
                            id: lineBtn
                            objectName: "lineBtn"
                            label: "直线"
                            iconName: "ic_fluent_line_20_regular"
                            fg: root.fgColor
                            bgHover: root.hoverColor
                            bgPressed: root.pressedColor
                            btnSize: root.btnSize
                            iconSize: root.btnIconSize
                            fontSize: root.btnFontSize
                            // 菜单打开 → 展开指示器旋转 180°（提示可收回）
                            showExpandIndicator: lineMenu.visible
                            expandIndicatorRotated: lineMenu.visible
                            // 单击弹线型菜单（再点收回）
                            onClicked: {
                                if (lineMenu.visible) {
                                    root.closeMenus()
                                } else {
                                    root.closeMenus()
                                    root.positionMenuAbove(lineMenu, lineBtn)
                                }
                            }
                        }
                    }
                    Item {
                        width: root.btnSize
                        height: root.btnSize
                        // 形状选中指示器：形状工具激活 **且选中的是图形** 时原地渐显（无位移动画）
                        Rectangle {
                            objectName: "shapeIndicator"
                            anchors.fill: parent
                            radius: width / 2
                            color: root.selectedColor
                            opacity: (lessonsBackend.activeTool === 3
                                      && root.isShapeStyle(lessonsBackend.lineStyle)) ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                            Behavior on color { ColorAnimation { duration: 150 } }
                        }
                        CircleToolButton {
                            id: shapeBtn
                            objectName: "shapeBtn"
                            label: "形状"
                            iconName: "ic_fluent_shapes_20_regular"
                            // 悬停效果与撤销按钮等一致：显示圆形半透明背景（不用 hoverFade）；
                            // 选中指示器（shapeIndicator）不受影响，仍按形状工具激活渐隐/渐显
                            fg: root.fgColor
                            bgHover: root.hoverColor
                            bgPressed: root.pressedColor
                            btnSize: root.btnSize
                            iconSize: root.btnIconSize
                            fontSize: root.btnFontSize
                            // 菜单打开 → 展开指示器旋转 180°（提示可收回）
                            // （测画方式菜单也是从这颗按钮弹的 → 一并计入）
                            showExpandIndicator: shapeMenu.visible || solidProjMenu.visible
                            expandIndicatorRotated: shapeMenu.visible || solidProjMenu.visible
                            // 单击弹形状菜单（选一种图形才开始绘制；再点收回）
                            onClicked: {
                                if (shapeMenu.visible || solidProjMenu.visible) {
                                    root.closeMenus()
                                } else {
                                    root.closeMenus()
                                    root.positionMenuAbove(shapeMenu, shapeBtn)
                                }
                            }
                        }
                    }
                }
            }
        }

        // 右胶囊：翻页/加页（白色 1px 边框 + 阴影）；末页时"下一页"替换为"加页"，页数最多 10 页
        Item {
            width: rightRow.width + root.capsulePad * 2
            height: root.capsuleH
            DropShadow {
                anchors.fill: parent
                source: rightCapsule
                radius: 20
                samples: 40
                color: "#22000000"
                transparentBorder: true
            }
            Rectangle {
                id: rightCapsule
                anchors.fill: parent
                radius: root.capsuleRadius
                color: root.capsuleColor
                border.width: 1
                border.color: "#33FFFFFF"
                Behavior on color { ColorAnimation { duration: 150 } }

                Row {
                    id: rightRow
                    anchors.centerIn: parent
                    spacing: 2
                    CircleToolButton {
                        objectName: "pagePrevBtn"
                        label: "上一页"
                        iconName: "ic_fluent_chevron_left_20_regular"
                        fg: root.fgColor
                        bgHover: root.hoverColor
                        bgPressed: root.pressedColor
                        btnSize: root.btnSize
                        iconSize: root.btnIconSize
                        fontSize: root.btnFontSize
                        enabled: whiteboardBackend.canGoPrev
                        opacity: whiteboardBackend.canGoPrev ? 1.0 : 0.35
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                        onClicked: {
                            root.closeMenus()
                            whiteboardBackend.prevPage()
                        }
                    }
                    // 页码指示器：圆形按钮（宽高相同 btnSize），图标位置显示"x / x"页码
                    // （字号稍大加粗），下方小字"页码"；点击弹出页面列表菜单（所有页缩略图/删除/切页）
                    Item {
                        id: pageIndicator
                        objectName: "pageIndicator"
                        width: root.btnSize
                        height: root.btnSize
                        // 文字行高近似（两行锚定布局用）
                        readonly property real _piRowH: root.btnFontSize * 1.2
                        Rectangle {
                            anchors.fill: parent
                            radius: width / 2
                            color: pageMa.pressed ? root.pressedColor
                                 : (pageMa.containsMouse ? root.hoverColor : "transparent")
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }
                        // 两行布局与其它按钮（CircleToolButton）一致：垂直居中+下移1px、spacing 2；
                        // 页码数值占据图标行高度（btnIconSize）并再上移 1px（容器内 y:-1）；
                        // "页码"文字字号（btnFontSize）/颜色与其它按钮文字相同，再上移 2px（y:-3，
                        // 用户反馈"页码"仍低 2px、页码数字低 1px）。
                        Column {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.verticalCenterOffset: 1
                            spacing: 2
                            Item {
                                width: root.btnSize
                                height: root.btnIconSize
                                Text {
                                    y: -3
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    width: root.btnSize
                                    height: root.btnIconSize
                                    verticalAlignment: Text.AlignVCenter
                                    horizontalAlignment: Text.AlignHCenter
                                    text: (whiteboardBackend.currentPage + 1) + " / " + whiteboardBackend.pageCount
                                    color: root.fgColor
                                    Behavior on color { ColorAnimation { duration: 150 } }
                                    font.family: Qt.application.font.family
                                    font.pixelSize: 15
                                    font.bold: true
                                }
                            }
                            Item {
                                width: root.btnSize
                                height: pageIndicator._piRowH
                                Text {
                                    y: -3
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "页码"
                                    color: root.fgColor
                                    Behavior on color { ColorAnimation { duration: 150 } }
                                    font.family: Qt.application.font.family
                                    font.pixelSize: root.btnFontSize
                                }
                            }
                        }
                        MouseArea {
                            id: pageMa
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                if (pageListMenu.visible) root.closeMenus()
                                else root.positionMenuAbove(pageListMenu, pageIndicator)
                            }
                        }
                    }
                    CircleToolButton {
                        objectName: "pageNextBtn"
                        // 末页：下一页按钮替换为"加页"（新增一页）；否则为下一页
                        readonly property bool onLastPage: whiteboardBackend.currentPage === whiteboardBackend.pageCount - 1
                        label: onLastPage ? "加页" : "下一页"
                        iconName: onLastPage ? "ic_fluent_add_20_regular" : "ic_fluent_chevron_right_20_regular"
                        fg: root.fgColor
                        bgHover: root.hoverColor
                        bgPressed: root.pressedColor
                        btnSize: root.btnSize
                        iconSize: root.btnIconSize
                        fontSize: root.btnFontSize
                        enabled: onLastPage ? whiteboardBackend.canAddPage : whiteboardBackend.canGoNext
                        opacity: enabled ? 1.0 : 0.35
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                        onClicked: {
                            root.closeMenus()
                            if (onLastPage) whiteboardBackend.addPage()
                            else whiteboardBackend.nextPage()
                        }
                    }
                }
            }
        }
    }

    // 笔工具菜单：粗细 + 颜色（右键笔按钮 / 已选中笔再点弹开；自绘 Item 置顶）
    PenMenu {
        id: penMenu
        objectName: "penMenu"
        z: 2000
        visible: false
        onWidthSelected: (w) => lessonsBackend.setPenWidth(w)
        onColorSelected: (c) => lessonsBackend.setPenColor(c)
    }

    // 擦除全屏菜单：圆形滑块拖到最右擦除全部笔迹（自绘 Item 置顶）
    EraserMenu {
        id: eraserMenu
        objectName: "eraserMenu"
        z: 2000
        visible: false
        onEraseAllRequested: {
            root.eraseAllRequested()
            root.closeMenus()   // 清屏后立即关闭菜单（滑块已在 EraserMenu 内部复位）
        }
    }

    // 线型菜单（原来的"形状 > 线"页搬到这里）：由工具栏"直线"按钮弹出。
    // 选中线型 → 切到形状工具，画完一条线自动回退到之前的工具。
    LineMenu {
        id: lineMenu
        objectName: "lineMenu"
        z: 2000
        visible: false
        onLineSelected: (style) => {
            lessonsBackend.setLineStyle(style)
            root.closeMenus()
            root.requestCloseAllMenus()
        }
    }

    // 形状菜单："平面图形" / "立体图形" / "坐标系"
    // 选中图形 → 切到形状工具，画完一个自动回退到之前的工具。
    ShapeMenu {
        id: shapeMenu
        objectName: "shapeMenu"
        z: 2000
        visible: false
        onLineSelected: (style) => {
            lessonsBackend.setLineStyle(style)
            root.closeMenus()
            root.requestCloseAllMenus()
            // 选中的是**支持选测画方式**的立体图形（圆柱 / 圆锥）→ 再弹一个测画方式菜单
            // （用户要求：关掉形状菜单，同时在形状按钮上方弹出它；选定后不关，
            //   直到开始画底面（点画布 → closeMenus）才关）
            // 用户要求：**每次选这类图形都回到默认的"正等测"**，不管上一次选了什么。
            // 菜单里的小图标随所选图形变（选圆锥就画圆锥，选圆柱就画圆柱）。
            if (whiteboardBackend.solidProjChoosable(style)) {
                whiteboardBackend.setSolidProjMode("iso")
                solidProjMenu.figureKind = style
                root.positionMenuAbove(solidProjMenu, shapeBtn)
            }
        }
    }

    // 立体图形测画方式菜单（正等测 / 斜二测）：由上面 shapeMenu 的选中处理弹出
    SolidProjMenu {
        id: solidProjMenu
        objectName: "solidProjMenu"
        z: 2000
        visible: false
        onProjSelected: (mode) => whiteboardBackend.setSolidProjMode(mode)
    }

    // 页面列表菜单：点击页码指示器弹出，列出所有页（缩略图/删除/切页）
    PageListMenu {
        id: pageListMenu
        objectName: "pageListMenu"
        z: 2000
        visible: false
        // 删页/加页使菜单高度变化 → 若可见则重新定位（贴住工具栏顶部，避免底部留空隙）
        onHeightChanged: {
            if (pageListMenu.visible) root.positionMenuAbove(pageListMenu, pageIndicator)
        }
    }
}
