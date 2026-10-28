import QtQuick 2.15
import QtQuick.Window 2.15
import Qt5Compat.GraphicalEffects
import RinUI
// 本地圆形按钮组件原名 ToolButton 与 RinUI 的 ToolButton 1.0 冲突（import RinUI 后会被覆盖、
// 导致 fontSize 等属性报错）——已改名为 CircleToolButton 避免冲突，此处置顶使用。

// 页面列表菜单（点击底部工具栏"页码指示器"弹出）：从上到下按第 1 页依次列出所有页。
// 每行：左侧当前页指示胶囊条（仅当前页：宽 4px/2px 圆角/黑或白填充/无边框，与页码数字留间距）
// + 页码数字 + 中间缩略图（高 96px，宽按画板比例，image://whiteboard/thumb 轻量渲染）
// + 右侧圆形删除按钮（图标+文字）。点击某行切换到该页；当前页行保留半透明填充高亮（无边框）。
// 底部"新建页面"胶囊按钮（左图标右文字，仅悬停/单击显示轮廓），点击在末尾加页并滚动到底。
// 菜单高度 = 页列表内容 + 新建区 + 上下内边距（小页数也完整显示），最多 640px 或屏幕容得下；
// 页数多时页列表可滚动（ListView 懒加载缩略图，性能好）。
// 背景/边框/阴影与工具栏一致。显示由 SpecialModeToolbar 通过 visible + x/y 定位控制。
Item {
    id: root
    objectName: "pageListMenu"

    // 强制重载全部缩略图：打开菜单时 + 内容变化（thumbsChanged：擦除/移动/撤销等）时都
    // 递增 reloadTick 并入缩略图 source → QML 重新请求渲染最新内容（不依赖 onVisibleChanged）。
    // 删除/加页不触发 thumbsChanged、也不全局 bump 版本 → 列表靠 ListView model 变化增量
    // 更新，避免全列表刷新/滚动失效；打开菜单时由下方 onVisibleChanged 兜底一次。
    property int reloadTick: 0
    onVisibleChanged: {
        if (visible) {
            reloadTick++
            syncPages()   // 打开时全量同步 ListModel + 强制缩略图重载（保证显示最新内容）
        }
    }
    Connections {
        target: whiteboardBackend
        function onThumbsChanged() {
            reloadTick++
        }
        function onPageAdded() {
            pageModel.append({})
        }
        function onPageRemoved(index) {
            if (index >= 0 && index < pageModel.count) pageModel.remove(index)
            // 删页后索引重排：后续 delegate 的缩略图 URL（page=N&v=..&o=..）会与删前的旧
            // 缓存 URL 相同（QML Image 按 URL 缓存命中 → 显示旧页缩略图）。必须递增
            // reloadTick 让所有缩略图的 o 参数变化 → 重新请求渲染最新内容。
            root.reloadTick++
        }
    }

    // 深浅色（与工具栏一致：白板=浅色）
    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property int capsuleRadius: 16

    // 当前页指示胶囊条：宽 4px、2px 圆角、黑/白填充、无边框
    readonly property color barColor: lightMode ? "#FF000000" : "#FFFFFFFF"

    // 行布局（坐标从行左边缘起）
    readonly property real barW: 3      // 当前页指示胶囊条宽（3px，圆角 ≥ 宽/2 → 胶囊）
    readonly property real barGap: 9    // 胶囊条与页码数字间距（合计 numLeft 仍是 12，数字/缩略图位置不变）
    readonly property real numW: 40     // 页码数字区宽（不含胶囊条）
    readonly property real gap: 8       // 元素间水平间距
    readonly property real thumbH: 96   // 缩略图高（适当缩小，视觉与点击都够用）
    readonly property real rowPad: 12   // 缩略图上下边距
    readonly property real rowH: thumbH + rowPad * 2   // 单行高 120
    readonly property real thumbW: Math.max(40, Math.round(whiteboardBackend.canvasAspect * thumbH))
    readonly property real delW: 56     // 删除按钮区宽
    readonly property real pad: 12      // 菜单左右/上下内边距
    readonly property real spacing: 6   // 行间距
    readonly property real newH: 44     // 底部"新建页面"按钮高
    readonly property real newGap: 8    // 新建按钮与页列表间距
    // 各元素 x（含当前页胶囊条预留）
    readonly property real numLeft: barW + barGap                       // 12
    readonly property real thumbLeft: numLeft + numW + gap              // 60
    readonly property real delLeft: thumbLeft + thumbW + gap
    readonly property real contentW: delLeft + delW
    readonly property real contentH: whiteboardBackend.pageCount * rowH
                                     + (whiteboardBackend.pageCount - 1) * spacing

    // 菜单高度：页列表内容 + 新建区 + 上下内边距（小页数也完整显示），最多 640px 或屏幕容得下。
    // 注意 root.Window 在无窗口（离屏/组件预览）时可能是 height=0 的无效 Window 而非 null，
    // 须同时判断 height>0，否则 availH 为负会把菜单高夹成 0。
    readonly property real winH: (root.Window && root.Window.height > 0) ? root.Window.height : 800
    readonly property real availH: winH - 120
    readonly property real menuH: Math.max(0, Math.min(contentH + newH + newGap + pad * 2, 640, availH))

    width: pad * 2 + contentW
    height: menuH

    // 阴影 + 背景（与工具栏/笔菜单一致）
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

    // 页列表 model：用 ListModel 增量同步（pageAdded/pageRemoved → append/remove）。
    // 若直接用 int model（pageCount），变化会让 ListView 重建全部 delegate → contentY 重置
    // （"整个列表刷新" + 新建后滚动到底失效）。ListModel 增量更新可保持滚动位置。
    ListModel {
        id: pageModel
    }
    function syncPages() {
        pageModel.clear()
        for (var i = 0; i < whiteboardBackend.pageCount; i++) {
            pageModel.append({})
        }
    }
    Component.onCompleted: syncPages()

    // 页列表：缩略图由 ImageProvider 惰性生成，ListView 只实例化可见行（滚动按需加载）
    ListView {
        id: list
        objectName: "pageList"
        x: root.pad
        y: root.pad
        width: parent.width - root.pad * 2
        height: Math.max(0, parent.height - root.pad * 2 - root.newH - root.newGap)
        model: pageModel
        spacing: root.spacing
        clip: true
        // 禁止越界回弹（overshoot）：addPage 后 contentY 会被弹到顶部（-11.22）再回弹，
        // 回弹动画会覆盖程序化设置的 contentY（新建页滚动到底失效）。StopAtBounds 禁掉它。
        boundsBehavior: Flickable.StopAtBounds

        delegate: Rectangle {
            id: row
            width: list.width
            height: root.rowH
            radius: 12
            // 当前页行：半透明填充高亮（无边框；原边框由左侧胶囊条替代）
            color: index === whiteboardBackend.currentPage
                   ? (root.lightMode ? "#14000000" : "#22FFFFFF") : "transparent"

            // 当前页指示胶囊条：宽 3px、圆角 ≥ 宽/2（胶囊）、高=缩略图高、黑/白填充、无边框
            Rectangle {
                visible: index === whiteboardBackend.currentPage
                x: 0
                anchors.verticalCenter: parent.verticalCenter
                width: root.barW
                height: root.thumbH
                radius: 2
                color: root.barColor
            }

            // 左侧页码数字（纯数字；当前页加粗、稍大；胶囊条右侧留间距）
            Text {
                x: root.numLeft
                width: root.numW
                anchors.verticalCenter: parent.verticalCenter
                text: index + 1
                color: root.fg
                horizontalAlignment: Text.AlignHCenter
                font.family: Qt.application.font.family
                font.pixelSize: index === whiteboardBackend.currentPage ? 15 : 13
                font.bold: index === whiteboardBackend.currentPage
            }

            // 行点击 → 切换到该页并关闭菜单（声明在删除按钮之前，删除按钮在上层优先）
            MouseArea {
                anchors.fill: parent
                onClicked: {
                    whiteboardBackend.switchToPage(index)
                    root.visible = false
                }
            }

            // 缩略图浅色底（透明画布上的笔迹在深浅模式下都可见）
            Rectangle {
                x: root.thumbLeft
                y: root.rowPad
                width: root.thumbW
                height: root.thumbH
                radius: 8
                color: root.lightMode ? "#0D000000" : "#14FFFFFF"
            }
            // 中间缩略图（高 thumbH，宽按画板比例；thumbVersion 变化时重新请求）
            Image {
                x: root.thumbLeft
                y: root.rowPad
                width: root.thumbW
                height: root.thumbH
                source: "image://whiteboard/thumb?page=" + index + "&v=" + whiteboardBackend.thumbVersion
                         + "&o=" + root.reloadTick
                fillMode: Image.PreserveAspectFit
                cache: true   // 相同 source 从 QML 缓存拿：删除/加页使 delegate 重建时不全部重渲染；
                              // reloadTick/thumbsChanged 变 source → 强制重新请求
            }

            // 右侧圆形删除按钮（图标+文字；后声明在上层 → 点击只删除不切页）
            CircleToolButton {
                x: root.delLeft
                anchors.verticalCenter: parent.verticalCenter
                label: "删除"
                iconName: "ic_fluent_delete_20_regular"
                fg: root.fg
                bgHover: root.lightMode ? "#0A000000" : "#20FFFFFF"
                bgPressed: root.lightMode ? "#10000000" : "#28FFFFFF"
                btnSize: 48
                iconSize: 18
                fontSize: 10
                onClicked: {
                    whiteboardBackend.deletePage(index)
                }
            }
        }
    }

    // 底部"新建页面"按钮：胶囊形，左图标右文字，仅悬停/单击时显示轮廓（边框+浅底）；
    // 页数已满（≥10，canAddPage=false）时禁用：半透明 + 无轮廓 + 点击无效
    Rectangle {
        id: newBtn
        objectName: "pageNewBtn"
        x: root.pad
        y: root.pad + list.height + root.newGap
        width: parent.width - root.pad * 2
        height: root.newH
        radius: root.newH / 2
        opacity: whiteboardBackend.canAddPage ? 1.0 : 0.4
        Behavior on opacity { NumberAnimation { duration: 120 } }
        color: whiteboardBackend.canAddPage && (nbMa.containsMouse || nbMa.pressed)
               ? (root.lightMode ? "#0A000000" : "#20FFFFFF") : "transparent"
        border.width: whiteboardBackend.canAddPage && (nbMa.containsMouse || nbMa.pressed) ? 1 : 0
        border.color: root.capsuleBorder
        Behavior on color { ColorAnimation { duration: 120 } }
        Row {
            anchors.centerIn: parent
            spacing: 6
            Icon {
                name: "ic_fluent_add_20_regular"
                size: 18
                color: root.fg
            }
            Text {
                text: "新建页面"
                color: root.fg
                font.family: Qt.application.font.family
                font.pixelSize: 13
            }
        }
        MouseArea {
            id: nbMa
            anchors.fill: parent
            hoverEnabled: true
            enabled: whiteboardBackend.canAddPage
            onClicked: root.createPage()
        }
    }

    // 新建页面：加页 + 平滑滚动到底。
    // 说明：addPage（pageModel.append）后 ListView 会把 contentY 重置到顶部（overshoot）并伴随
    // 回弹动画（真机约 100ms、离屏更久），期间设置 contentY 会被覆盖。方案：先置顶，等回弹
    // 完全结束（短周期采样检测 contentY 稳定在 0 附近），再用 NumberAnimation 平滑滚动到底——
    // 不再"抖动后闪现到底"。回弹不算 Flickable.moving，onMovingChanged 不可靠。
    function createPage() {
        root.pendingScrollEnd = true
        root.settleStableCount = 0
        root.settleTicks = 0
        root.animRefired = false
        settleTimer.start()
        whiteboardBackend.addPage()
        list.contentY = 0   // 置顶消化 append 后的一次性重置
    }

    // 平滑滚动到底部：NumberAnimation 驱动 contentY（从当前值动画到 contentHeight-height）。
    // 内容不满一屏（目标 < 0）时归 0 即可；动画结束后 contentHeight 若再变（懒加载）则补滚一次。
    function animateToEnd() {
        if (!list) return
        var to = list.contentHeight - list.height
        if (to < 1) to = 0
        scrollToEndAnim.stop()
        scrollToEndAnim.to = to
        scrollToEndAnim.start()
    }

    // 等 append 的重置+回弹结束（contentY 稳定在 0 附近），随后平滑滚动到底；2s 未稳定强制滚（兜底）。
    property bool pendingScrollEnd: false
    property int settleStableCount: 0
    property int settleTicks: 0
    property bool animRefired: false
    Timer {
        id: settleTimer
        interval: 50
        repeat: true
        onTriggered: {
            if (!root.pendingScrollEnd) { stop(); return }
            root.settleTicks++
            var cy = list ? list.contentY : 0
            if (Math.abs(cy) < 0.05) {
                root.settleStableCount++
                if (root.settleStableCount >= 2) {
                    root.pendingScrollEnd = false
                    stop()
                    root.animateToEnd()
                    return
                }
            } else {
                root.settleStableCount = 0
            }
            if (root.settleTicks >= 40) {   // 2s 兜底
                root.pendingScrollEnd = false
                stop()
                root.animateToEnd()
            }
        }
    }

    NumberAnimation {
        id: scrollToEndAnim
        target: list
        property: "contentY"
        duration: 350
        easing.type: Easing.OutCubic
        onFinished: {
            // contentHeight 懒加载变化导致不在底部 → 补滚一次（最多一次）
            if (!list || root.animRefired) return
            var to = list.contentHeight - list.height
            if (to > 0 && Math.abs(list.contentY - to) > 1) {
                root.animRefired = true
                scrollToEndAnim.to = to
                scrollToEndAnim.start()
            }
        }
    }
    Connections {
        target: list
        function onContentHeightChanged() {
            // contentHeight 更新（新页）时：若正在等回弹结束，重置稳定计数并重启采样
            // （避免用旧高度判稳）；平滑动画进行中则由 onFinished 补滚一次。
            if (root.pendingScrollEnd) {
                root.settleStableCount = 0
                settleTimer.restart()
            }
        }
    }
}
