import QtQuick 2.15
import RinUI
import QtQuick.Window 2.15

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

    // 绘制鼠标区：笔/橡皮工具按下拖动绘制；层级在课程条之上（可在课程列表区域绘制），
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
        enabled: settingsBackend.getString("device_type") === "interactive_panel"
                 && (lessonsBackend.activeTool === 1 || lessonsBackend.activeTool === 2)
                 && root.visible
        onPressed: (mouse) => {
            if (mouse.button !== Qt.LeftButton) return
            // 点击画布时关闭已打开的工具栏菜单
            var tbi = toolbarLoader.item
            if (tbi && tbi.closeMenus) tbi.closeMenus()
            penDown = true
            lastPt = Qt.point(mouse.x, mouse.y)
            if (lessonsBackend.activeTool === 1) {
                whiteboardBackend.beginStroke(0, lessonsBackend.penColor, lessonsBackend.penWidth, mouse.x, mouse.y)
            } else {
                whiteboardBackend.beginStroke(1, "", 32, mouse.x, mouse.y)  // 橡皮直径 = 2*16px
            }
        }
        onPositionChanged: (mouse) => {
            if (!penDown) return
            if (Math.abs(mouse.x - lastPt.x) < 1 && Math.abs(mouse.y - lastPt.y) < 1) return
            lastPt = Qt.point(mouse.x, mouse.y)
            whiteboardBackend.moveStroke(mouse.x, mouse.y)
        }
        onReleased: {
            if (!penDown) return
            penDown = false
            whiteboardBackend.endStroke()
        }
        onCanceled: {
            if (penDown) {
                penDown = false
                whiteboardBackend.endStroke()
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
        source: "SpecialModeToolbar.qml"
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
