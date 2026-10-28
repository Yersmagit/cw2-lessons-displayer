import QtQuick 2.15
import RinUI

// 两阶段图形（椭圆 / 双曲线 / 扇形 / 立体图形）第二阶段的**探针手柄层**（层级由 SpecialModeWindow 指定 z55）：
// - 后端 focusProbeHandles 给出手柄位置（椭圆/双曲线 = 两焦点；扇形 = 第一条半径中点；
//   **立体图形 = 底面中心（升降手柄，只占 1 个）**；正在拖的那个跟鼠标）；
// - 每个手柄 = 圆形白色手柄（黑 1px 边框）+ 图标（**立体图形的图标是上下双向箭头** ——
//   拖它做升维，见后端 focusHandleIcon），都可拖；
// - 拖拽中**手柄视觉隐藏**（圆 + 图标不可见，但 Item 与 MouseArea 保留以维持鼠标 grab），
//   后端按探针重算形状（椭圆：2a = 探针到两焦点距离和；双曲线：几何重心→探针 是一条渐近线），
//   "几何重心→鼠标"的蓝色虚线由 SpecialModeWindow 的 Canvas 画出（后端 figureSnapGuide）；
// - 松手 → 后端提交形状并发 shapeFinished（工具回退到之前的选择/笔/橡皮）。
//
// 注意：**不要用 Repeater + 持续变化的 QVariantList 模型**——后端每帧刷新都会让模型
// 变成"新数组"，Repeater 会重建 delegate，正在拖的那个 MouseArea 被销毁 → 收不到
// onReleased（松手不提交、手柄卡住）。所以这里用两个固定实例（位置绑定后端数据）。
Item {
    id: root
    objectName: "focusHandles"

    readonly property var handles: whiteboardBackend.focusProbeHandles
    // 手柄个数：椭圆/双曲线 = 2（两焦点）；**扇形 / 立体图形 = 1**
    readonly property int count: (handles !== undefined && handles !== null) ? handles.length : 0
    readonly property bool active: whiteboardBackend.focusProbeActive === true && count >= 1
    // 手柄里的图标：**立体图形 = 上下双向箭头**（升维），其余 = 移动图标（后端属性）
    readonly property string handleIcon: whiteboardBackend.focusHandleIcon
    readonly property real visR: 12     // 视觉圆半径（比选择层四角手柄 r10 稍大，能容下大图标）
    readonly property real hitR: 16     // 命中半宽（视觉圆 + 外扩）
    // 是否正在拖某个手柄：拖拽中把手柄视觉隐藏（不挡视线）。
    // **注意：只隐藏“圆 + 图标”两个视觉子项，绝对不能把整个 Item/HouseArea 隐藏**——
    // 不可见的 MouseArea 会丢掉鼠标 grab → onPositionChanged/onReleased 全部收不到（拖不动/不提交）。
    property bool dragging: false
    // 后端探针拖拽标志：**在画布任意位置自由拖拽时也要隐藏手柄**（用户要求），
    // 而那时本地 dragging 为 false（没按到手柄）→ 两个标志取或。
    readonly property bool probeDragging: whiteboardBackend.focusProbeDragging === true
    readonly property bool hideVisual: dragging || probeDragging
    // 手柄位置（未给到的手柄留 0；反正整层此时不可见、不接收鼠标）
    readonly property real px0: (active && count >= 1) ? handles[0][0] : 0
    readonly property real py0: (active && count >= 1) ? handles[0][1] : 0
    readonly property real px1: (active && count >= 2) ? handles[1][0] : 0
    readonly property real py1: (active && count >= 2) ? handles[1][1] : 0

    visible: active
    enabled: active
    // 第二阶段可能被别处结束（如拖拽中在画布按下 → 后端提交形状）→ 复位拖拽标志
    onActiveChanged: if (!active) dragging = false

    component FocusHandle: Item {
        id: handle
        property int idx: 0
        property real px: 0
        property real py: 0
        // 拖拽中隐藏视觉（圆 + 图标），但 Item 与 MouseArea 保持存在
        property bool showVisual: !root.hideVisual
        objectName: "focusHandle_" + handle.idx
        width: root.hitR * 2
        height: root.hitR * 2
        x: handle.px - root.hitR
        y: handle.py - root.hitR

        Rectangle {
            objectName: "focusHandleVis"
            visible: handle.showVisual
            anchors.centerIn: parent
            width: root.visR * 2
            height: root.visR * 2
            radius: root.visR
            color: "white"
            border.width: 1
            border.color: "black"
        }
        // 图标尺寸 18 + 下移 1px：实测（离屏 1x 像素量测）这套组合下图标墨迹的
        // 包围盒中心与圆心完全重合（dx=dy=0.00）；漏掉 verticalCenterOffset 会高 1px、
        // 沿用旧的 14px 则会左偏 1px（这正是“图标不居中”的根源）。
        Icon {
            objectName: "focusHandleIcon"
            visible: handle.showVisual
            anchors.centerIn: parent
            anchors.verticalCenterOffset: 1
            name: root.handleIcon
            size: 18
            color: "black"
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.SizeAllCursor
            // 注意：QML 的展开语法 `...` 只对数组有效，`mapToItem` 返回的是 point
            // （曾用 `...mapToItem(...)` → 参数传不进去，只在 stderr 里报 TypeError）
            onPressed: (m) => {
                root.dragging = true
                var p = mapToItem(root, m.x, m.y)
                whiteboardBackend.beginFocusProbe(handle.idx, p.x, p.y)
            }
            onPositionChanged: (m) => {
                var p = mapToItem(root, m.x, m.y)
                whiteboardBackend.dragFocusProbe(p.x, p.y)
            }
            onReleased: {
                root.dragging = false
                whiteboardBackend.endFocusProbe()
            }
            onCanceled: {
                root.dragging = false
                whiteboardBackend.endFocusProbe()
            }
        }
    }

    FocusHandle { idx: 0; px: root.px0; py: root.py0 }
    // 扇形 / 立体图形只有 1 个手柄 → 第二个手柄整个隐藏（不可见即不接收鼠标）
    FocusHandle { idx: 1; px: root.px1; py: root.py1; visible: root.count >= 2 }
}
