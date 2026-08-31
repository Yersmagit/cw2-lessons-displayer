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

    // 二级菜单显示在相应按钮上方，菜单底部距工具栏顶部 8px（水平居中于按钮）。
    // 菜单是工具栏子对象，y 为负表示在工具栏上方空间（窗口内）。
    function positionMenuAbove(menu, anchorItem) {
        menu.visible = true
        var tl = anchorItem.mapToItem(root, 0, 0)
        menu.x = tl.x + anchorItem.width / 2 - menu.width / 2
        menu.y = -menu.height - 8
        if (menu.x < 0) menu.x = 0
    }
    function closeMenus() {
        penMenu.visible = false
        eraserMenu.visible = false
    }
    // 是否有菜单打开（供 SpecialModeWindow 的菜单外点击关闭层判断）
    readonly property bool menusOpen: penMenu.visible || eraserMenu.visible

    // 窗口可见性（由 SpecialModeWindow 绑定）：true→淡入，false→渐隐
    property bool windowVisible: false

    // 设备类型非交互智能平板 → 不显示
    visible: settingsBackend.getString("device_type") === "interactive_panel"
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
                    ToolButton {
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
                    ToolButton {
                        // 切换按钮：文字显示将切换到的实际模式，图标用太阳/月亮（白板→熄屏月亮、熄屏→白板太阳）
                        label: lessonsBackend.mode === "whiteboard" ? "熄屏模式" : "白板模式"
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

                        // 选中指示器：始终存在的半透明圆表示当前选中项，切换时平移到对应项（动画）
                        Rectangle {
                            id: segIndicator
                            objectName: "segIndicator"
                            width: root.btnSize
                            height: root.btnSize
                            radius: width / 2
                            color: root.selectedColor
                            Behavior on color { ColorAnimation { duration: 150 } }
                            x: segRow.x + (segCapsule.segIndex === 0 ? segSelectBtn.x
                                              : segCapsule.segIndex === 1 ? segPenBtn.x : segEraserBtn.x)
                            Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                        }

                        Row {
                            id: segRow
                            spacing: 2
                            ToolButton {
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
                            ToolButton {
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
                                // 已选中笔时再点 → 弹笔菜单（再点切换关闭）；右键 → 弹笔菜单
                                onClicked: {
                                    if (segCapsule.segIndex === 1) {
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
                            ToolButton {
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
                                // 已选中橡皮时再点 → 弹擦除全屏菜单（再点切换关闭）；右键 → 弹擦除全屏菜单
                                onClicked: {
                                    if (segCapsule.segIndex === 2) {
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
                    ToolButton {
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
                    ToolButton {
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
                    // 页码指示（n / m）
                    Item {
                        width: 48
                        height: root.btnSize
                        Text {
                            anchors.centerIn: parent
                            text: (whiteboardBackend.currentPage + 1) + " / " + whiteboardBackend.pageCount
                            color: root.fgColor
                            Behavior on color { ColorAnimation { duration: 150 } }
                            font.family: Qt.application.font.family
                            font.pixelSize: 14
                        }
                    }
                    ToolButton {
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
        onEraseAllRequested: root.eraseAllRequested()
    }
}
