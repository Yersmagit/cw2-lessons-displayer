import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 选中笔划的浮动工具栏（自绘 Item）：形态/大小/配色/阴影与底部工具栏一致；
// 层级高于底部工具栏、低于设置蒙层（由 SpecialModeWindow 以 z1001 放置）。
// 尽量在选中矩形下方 8px 弹出；下方空间不够（超出屏幕）则贴到屏幕最底部；
// 水平居中于矩形并夹在屏幕内。
// 提供"克隆/删除/粗细/颜色"四个选项（选中全是形状线时再加一个"线型"），点击弹出二级菜单
// （有空间在上方，否则在下方）；选择后同时调整选中笔划的样式（由 WhiteboardBackend
// 的 setSelectionXXX 处理并记录撤销）。
Item {
    id: root
    objectName: "selectionToolbar"

    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fgColor: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color hoverColor: lightMode ? "#0A000000" : "#20FFFFFF"
    readonly property color pressedColor: lightMode ? "#10000000" : "#28FFFFFF"
    readonly property int btnSize: 52
    readonly property int btnIconSize: 22
    readonly property int btnFontSize: 12
    readonly property int capsulePad: 4
    // 胶囊高度 = 按钮高 + 上下各一个 capsulePad：保证按钮上边缘到工具栏上边框
    // 的距离与两侧按钮到工具栏左右端的距离**相等**（底部工具栏同此关系）。
    readonly property int capsuleH: root.btnSize + root.capsulePad * 2
    readonly property int capsuleRadius: capsuleH / 2

    // 仅"选中笔划存在"且处于"选择"工具时显示
    visible: whiteboardBackend.hasSelection && lessonsBackend.activeTool === 0

    width: row.width + root.capsulePad * 2
    height: root.capsuleH

    // 阴影（与工具栏一致：半透明灰 13%）
    DropShadow {
        anchors.fill: parent
        source: bgRect
        radius: 20
        samples: 40
        color: "#22000000"
        transparentBorder: true
    }
    Rectangle {
        id: bgRect
        anchors.fill: parent
        radius: root.capsuleRadius
        color: root.capsuleColor
        border.width: 1
        border.color: "#33FFFFFF"
    }
    Row {
        id: row
        anchors.centerIn: parent
        spacing: 2
        CircleToolButton {
            objectName: "selCloneBtn"
            label: "克隆"
            iconName: "ic_fluent_copy_20_regular"
            fg: root.fgColor
            bgHover: root.hoverColor
            bgPressed: root.pressedColor
            btnSize: root.btnSize
            iconSize: root.btnIconSize
            fontSize: root.btnFontSize
            // 单击克隆选中笔迹（偏移复制一份），旧笔迹取消选中、新笔迹选中
            onClicked: {
                root.closeMenus()
                whiteboardBackend.cloneSelection()
            }
        }
        CircleToolButton {
            objectName: "selDeleteBtn"
            label: "删除"
            iconName: "ic_fluent_delete_20_regular"
            fg: root.fgColor
            bgHover: root.hoverColor
            bgPressed: root.pressedColor
            btnSize: root.btnSize
            iconSize: root.btnIconSize
            fontSize: root.btnFontSize
            // 单击直接删除选中笔迹（可撤销），删除后选择自动清除、工具栏隐藏
            onClicked: {
                root.closeMenus()
                whiteboardBackend.deleteSelection()
            }
        }
        CircleToolButton {
            objectName: "selWidthBtn"
            label: "粗细"
            iconName: "ic_fluent_line_20_regular"
            fg: root.fgColor
            bgHover: root.hoverColor
            bgPressed: root.pressedColor
            btnSize: root.btnSize
            iconSize: root.btnIconSize
            fontSize: root.btnFontSize
            onClicked: root.toggleMenu(widthMenu, this)
        }
        CircleToolButton {
            objectName: "selColorBtn"
            label: "颜色"
            iconName: "ic_fluent_color_20_regular"
            fg: root.fgColor
            bgHover: root.hoverColor
            bgPressed: root.pressedColor
            btnSize: root.btnSize
            iconSize: root.btnIconSize
            fontSize: root.btnFontSize
            onClicked: root.toggleMenu(colorMenu, this)
        }
        CircleToolButton {
            objectName: "selLineStyleBtn"
            label: "线型"
            iconName: "ic_fluent_line_style_20_regular"
            // 仅当“选中项全是形状线”时提供（手绘笔迹没有线型概念）；隐藏时宽度归零
            // 以免在 Row 里占位
            visible: whiteboardBackend.selectionLineHandles.length > 0
            width: visible ? root.btnSize : 0
            fg: root.fgColor
            bgHover: root.hoverColor
            bgPressed: root.pressedColor
            btnSize: root.btnSize
            iconSize: root.btnIconSize
            fontSize: root.btnFontSize
            onClicked: root.toggleMenu(lineStyleMenu, this)
        }
    }

    // 二级菜单：自绘置顶子对象，由 showMenu 定位（有空间在上方，否则下方）
    SelectionMenu {
        id: widthMenu
        objectName: "widthMenu"
        kind: "width"
        title: "粗细"
        selectedWidth: whiteboardBackend.selectionWidth
        selectedColor: whiteboardBackend.selectionColor
        z: 2000
        visible: false
        onWidthSelected: (w) => whiteboardBackend.setSelectionWidth(w)
    }
    SelectionMenu {
        id: colorMenu
        objectName: "colorMenu"
        kind: "color"
        title: "颜色"
        selectedWidth: whiteboardBackend.selectionWidth
        selectedColor: whiteboardBackend.selectionColor
        z: 2000
        visible: false
        onColorSelected: (c) => whiteboardBackend.setSelectionColor(c)
    }
    // 线型菜单：直线/虚线/点虚线/波浪线/点状虚线/双实线/箭头/双向箭头/光线/剖面线
    // （仅选中全是线时可用）
    SelectionMenu {
        id: lineStyleMenu
        objectName: "lineStyleMenu"
        kind: "linestyle"
        title: "线型"
        selectedWidth: whiteboardBackend.selectionWidth
        selectedColor: whiteboardBackend.selectionColor
        z: 2000
        visible: false
        onLineStyleSelected: (sid) => whiteboardBackend.setSelectionLineStyle(sid)
    }

    function toggleMenu(menu, btn) {
        if (menu.visible) { closeMenus(); return }
        closeMenus()
        showMenu(menu, btn)
    }
    // 二级菜单：优先在按钮上方（工具栏坐标），上方放不下（全局 y<0）则在下方
    function showMenu(menu, btn) {
        menu.visible = true
        var tl = btn.mapToItem(root, 0, 0)
        menu.x = tl.x + btn.width / 2 - menu.width / 2
        var winW = root.parent ? root.parent.width : 0
        menu.x = Math.max(-root.x, Math.min(winW - root.x - menu.width, menu.x))
        var yAboveGlobal = root.y + tl.y - menu.height - 8
        if (yAboveGlobal >= 0) menu.y = tl.y - menu.height - 8
        else menu.y = tl.y + btn.height + 8
    }
    function closeMenus() {
        widthMenu.visible = false
        colorMenu.visible = false
        lineStyleMenu.visible = false
    }
    readonly property bool menusOpen: widthMenu.visible || colorMenu.visible
                                      || lineStyleMenu.visible

    // 位置：尽量在选中矩形下方弹出；下方空间不够（会超出屏幕）则贴到屏幕最底部。
    // 水平居中于矩形并夹在屏幕内。
    function reposition() {
        var r = whiteboardBackend.selectionRect
        if (!r || r.length < 4) return
        var winW = root.parent ? root.parent.width : 0
        var winH = root.parent ? root.parent.height : 0
        var cx = r[0] + r[2] / 2
        var y = r[1] + r[3] + 8
        if (y + root.height > winH)
            y = winH - root.height     // 下方放不下 → 尽量贴最底部
        if (y < 0) y = 0
        root.y = y
        root.x = Math.max(0, Math.min(winW - root.width, cx - root.width / 2))
    }
    Connections {
        target: whiteboardBackend
        function onSelectionChanged() { root.reposition() }
    }
    Connections {
        target: lessonsBackend
        function onActiveToolChanged() { root.reposition() }
    }
    // 显示时重新定位；隐藏（切走选择工具）时关闭二级菜单（否则其仍占用菜单关闭层）
    onVisibleChanged: {
        if (visible) reposition()
        else closeMenus()
    }
    // 按钮数量变化（选中项全是线时多出“线型”一项）会让 Row 宽度在布局抛光后才更新，
    // 而首次 reposition() 可能发生在宽度更新之前 → 按旧宽度居中会偏右；
    // 宽度一变就重新夹取一次 x。
    onWidthChanged: if (visible) reposition()
    Component.onCompleted: reposition()
}
