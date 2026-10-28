import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
import RinUI

Item {
    id: root
    height: 54 * lessonsBackend.scaleFactor

    // ===== 悬停渐隐（跟随主程序 interactions.hover_fade）=====
    // 开启（仅一般模式；迷你模式同样生效——Python 判定点会反向 0.7 映射到源坐标）时：
    // 透明度因子由 lessonsBackend.hoverFadeFactor（Python 全局鼠标坐标轮询驱动：按钮区 1 /
    // 胶囊内非按钮 0.25 / 移出 1）驱动，渐隐/恢复带 200ms 渐变；非按钮区（课程列表带）由
    // fadeBlock 拦截——不再接受鼠标事件（不滚动/不拖动），按钮区正常可点且有 hover。
    readonly property bool hoverFadeActive: lessonsBackend.hoverFade
        && lessonsBackend.mode === "normal"
    opacity: lessonsBackend.hoverFadeFactor
    Behavior on opacity {
        NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
    }

    // 根据模式计算实际暗色主题
    readonly property bool effectiveDarkTheme: {
        if (lessonsBackend.mode === "whiteboard") return false
        if (lessonsBackend.mode === "blackboard") return true
        return lessonsBackend.isDarkTheme
    }

    // 交互智能平板（区别于投影设备或其他）：决定顶栏按钮形态与设置页文案
    readonly property bool isInteractivePanel: settingsBackend.deviceType === "interactive_panel"

    // 特殊模式 + 交互智能平板（底部工具栏显示）时隐藏顶部圆形按钮（工具栏已提供退出/切换）
    readonly property bool showTopButtons: lessonsBackend.mode === "normal"
        || !root.isInteractivePanel

    // 背景颜色：特殊模式纯色，正常模式半透明（透明度已乘系数）
    readonly property color bgColor: {
        if (lessonsBackend.mode === "whiteboard") {
            return Qt.rgba(255/255, 255/255, 255/255, 1)   // 纯白
        } else if (lessonsBackend.mode === "blackboard") {
            return Qt.rgba(0/255, 0/255, 0/255, 1)         // 纯黑
        } else {
            if (effectiveDarkTheme) {
                return Qt.rgba(30/255, 29/255, 34/255, 0.65 * lessonsBackend.bgOpacity)
            } else {
                return Qt.rgba(251/255, 250/255, 255/255, 0.7 * lessonsBackend.bgOpacity)
            }
        }
    }

    // 边框基础颜色（用于渐变）
    readonly property color borderBaseColor: effectiveDarkTheme
        ? Qt.rgba(255/255, 255/255, 255/255, 0.4)
        : Qt.rgba(255/255, 255/255, 255/255, 1)

    readonly property real borderWidth: 1.5 * lessonsBackend.scaleFactor
    // 外围胶囊圆角：跟随主程序"小组件圆角半径"配置（lessonsBackend.widgetRadius 已换算）
    readonly property real radius: lessonsBackend.widgetRadius * lessonsBackend.scaleFactor

    // 背景矩形（纯色，无边框）—— 添加颜色动画
    Rectangle {
        id: backgroundRect
        anchors.fill: parent
        radius: root.radius
        color: bgColor
        Behavior on color {
            ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
        }
    }

    // 渐变边框层（仅在正常模式下显示）
    Item {
        anchors.fill: parent
        z: 1
        visible: lessonsBackend.mode === "normal"
        opacity: 0.85 * lessonsBackend.bgOpacity
        Behavior on opacity {
            NumberAnimation { duration: 400; easing.type: Easing.OutCubic }
        }

        Rectangle {
            id: borderRect
            anchors.fill: parent
            radius: root.radius
            color: "white"
            layer.enabled: true
            layer.effect: LinearGradient {
                start: Qt.point(width * 0.47, 0)
                end: Qt.point(width * 0.55, height)
                gradient: Gradient {
                    GradientStop { position: 0; color: borderBaseColor }
                    GradientStop { position: 0.3; color: Qt.rgba(1,1,1,0) }
                    GradientStop { position: 0.7; color: Qt.rgba(1,1,1,0) }
                    GradientStop { position: 1; color: borderBaseColor }
                }
            }
        }

        layer.enabled: true
        layer.effect: OpacityMask {
            maskSource: Rectangle {
                width: borderRect.width
                height: borderRect.height
                radius: borderRect.radius
                color: "transparent"
                border.width: borderWidth
            }
        }
    }

    // 内容容器（手动布局）
    Row {
        id: contentRow
        anchors.fill: parent
        spacing: 0

        // 左侧固定边距
        Item { width: 13 * lessonsBackend.scaleFactor; height: parent.height }

        // 换课按钮：单击打开主程序换课窗口；悬停显示"换课"提示
        RoundButton {
            id: switchButton
            objectName: "topSwitchButton"
            enabled: true
            visible: root.showTopButtons
            hoverEnabled: true
            implicitWidth: 30 * lessonsBackend.scaleFactor
            implicitHeight: 30 * lessonsBackend.scaleFactor
            icon.name: "ic_fluent_arrow_swap_20_regular"
            icon.width: 18 * lessonsBackend.scaleFactor
            icon.height: 18 * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
            onClicked: {
                lessonsBackend.openClassSwap()
            }
        }

        Item { width: 8 * lessonsBackend.scaleFactor; height: parent.height; visible: root.showTopButtons }

        // 左侧居中空白：内容放得下时把列表夹在中间；放不下时宽度为 0，列表占满剩余空间
        Item {
            id: leftSpacer
            height: parent.height
            width: centerSpacerWidth()
        }

        // ========== 课程列表 ==========
        ListView {
            id: lessonsListView
            objectName: "lessonsListView"
            orientation: ListView.Horizontal
            spacing: 5 * lessonsBackend.scaleFactor
            clip: true
            height: (lessonsBackend.mode === "normal" ? 40 : 46) * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
            // 视口宽度 = 可用宽度 - 两侧 spacer：放得下时居中（contentX=0），放不下时占满剩余空间自动滚动
            width: availableListViewWidth() - leftSpacer.width - rightSpacer.width

            // 模型改为 displayItems，包含课程和分隔符
            model: lessonsBackend.displayItems

            // 预实例化全部 delegate（课程数有限，开销可忽略），保证 itemAtIndex 返回真实几何，避免滚动定位错误
            displayMarginBeginning: 10000
            displayMarginEnd: 10000

            // 自动滚动相关属性
            property bool autoScrollEnabled: true
            property bool userInteracted: false
            property bool hovered: false
            property bool scrollBarVisible: false
            // 自动滚动防抖：同一目标每秒请求不打断/重启动画（避免 contentX 原地抖动）
            property int lastScrollIndex: -1
            property real lastTargetX: -1
            property bool scrollAnimating: false

            // 宽度变化（尤其放得下→放不下）瞬态布局未稳，清空锁定并用 Qt.callLater 延迟权威定位；
            // 期间视口宽度连续变化会闪动滚动条，未悬停则暂时隐藏
            onWidthChanged: {
                lastScrollIndex = -1
                lastTargetX = -1
                if (!hovered) scrollBarVisible = false
                Qt.callLater(function() { relayoutScroll() })
            }
            onContentWidthChanged: {
                lastScrollIndex = -1
                lastTargetX = -1
                Qt.callLater(function() { relayoutScroll() })
            }

            // 宽度/内容宽度变化后延迟重定位：放得下则 contentX 归零（居中）；
            // 放不下则无动画直接对齐到当前高亮课程（宽度变化期间用动画重定位会反复
            // stop+start 滚动动画，产生横向抖动/抽搐）。
            function relayoutScroll() {
                if (contentWidth <= width) {
                    if (contentX !== 0) contentX = 0
                    return
                }
                if (!autoScrollEnabled) return
                // 停止可能正在运行的滚动动画，避免其继续把 contentX 拉回旧目标
                if (scrollAnimation.running) scrollAnimation.stop()
                var targetId = lessonsBackend.currentLessonId || lessonsBackend.nextLessonId
                if (!targetId) return
                var items = lessonsBackend.displayItems
                for (var i = 0; i < items.length; i++) {
                    if (items[i].type === "lesson" && items[i].id === targetId) {
                        var targetX = computeTargetX(i)
                        if (isNaN(targetX) || targetX < 0) return  // 布局未稳定，等下一次
                        lastScrollIndex = i
                        lastTargetX = targetX
                        if (Math.abs(contentX - targetX) > 1) contentX = targetX
                        break
                    }
                }
            }

            // 滚动条隐藏延迟定时器
            Timer {
                id: hideScrollBarTimer
                interval: 1000
                onTriggered: {
                    lessonsListView.scrollBarVisible = false
                }
            }

            function updateScrollBarVisible(show) {
                if (show) {
                    scrollBarVisible = true
                    hideScrollBarTimer.stop()
                } else {
                    hideScrollBarTimer.restart()
                }
            }

            function pauseAutoScroll() {
                autoScrollEnabled = false
                userInteracted = true
                // 用户操作滚动后延迟 4 秒恢复自动滚动（统一重启定时器，避免某路径遗漏而永久卡死）
                userInteractionTimer.restart()
            }

            Timer {
                id: userInteractionTimer
                interval: 4000
                onTriggered: {
                    lessonsListView.autoScrollEnabled = true
                    lessonsListView.userInteracted = false
                    if (lessonsListView.contentWidth > lessonsListView.width) {
                        lessonsListView.scrollToCurrentLesson()
                    }
                }
            }

            onMovementStarted: {
                pauseAutoScroll()
                updateScrollBarVisible(true)
                // 用户拖拽开始立即停止自动滚动动画，避免抢 contentX
                if (scrollAnimation.running) scrollAnimation.stop()
            }

            onMovementEnded: {
                userInteractionTimer.restart()
            }

            HoverHandler {
                id: listHoverHandler
                acceptedDevices: PointerDevice.Mouse
                onHoveredChanged: {
                    lessonsListView.hovered = hovered
                    if (hovered) {
                        lessonsListView.updateScrollBarVisible(true)
                    } else {
                        lessonsListView.updateScrollBarVisible(false)
                    }
                }
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                propagateComposedEvents: true
                onWheel: (wheel) => {
                    lessonsListView.pauseAutoScroll()
                    userInteractionTimer.restart()
                    lessonsListView.updateScrollBarVisible(true)

                    if (wheel.angleDelta.y !== 0 && lessonsListView.contentWidth > lessonsListView.width) {
                        var step = wheel.angleDelta.y > 0 ? -150 : 150
                        var targetX = lessonsListView.contentX + step
                        targetX = Math.max(0, Math.min(targetX, lessonsListView.contentWidth - lessonsListView.width))
                        if (Math.abs(targetX - lessonsListView.contentX) < 1) return
                        if (scrollAnimation.running) scrollAnimation.stop()
                        scrollAnimation.to = targetX
                        scrollAnimation.start()
                        wheel.accepted = true
                    }
                }
            }

            // 委托：根据类型渲染课程或分隔符
            delegate: Loader {
                id: delegateLoader
                // 暴露 index，便于 computeTargetX 定位目标项真实几何（也便于测试）
                property int itemIndex: index
                sourceComponent: {
                    if (modelData.type === "separator") {
                        return separatorComponent
                    } else if (modelData.type === "placeholder") {
                        return placeholderComponent
                    } else {
                        return lessonComponent
                    }
                }

                // 课程项组件
                Component {
                    id: lessonComponent
                    Item {
                        id: lessonItem
                        property bool isHighlighted: modelData.id === lessonsBackend.currentLessonId || (lessonsBackend.currentState === 0 && modelData.id === lessonsBackend.nextLessonId)
                        property bool expanded: isHighlighted && lessonsBackend.mode !== "normal"
                        // 折叠宽度固定为缩写宽度 + 10，不依赖模式
                        property real foldedWidth: lessonAbbr.contentWidth + 10 * lessonsBackend.scaleFactor
                        // 展开宽度根据实际内容计算（仅在特殊模式下使用）
                        property real expandedWidth: 30 * lessonsBackend.scaleFactor + 8 * lessonsBackend.scaleFactor + lessonFullName.contentWidth + 22 * lessonsBackend.scaleFactor + remainingText.implicitWidth + 20 * lessonsBackend.scaleFactor
                        property real targetWidth: foldedWidth

                        width: targetWidth
                        height: (lessonsBackend.mode === "normal" ? 40 : 46) * lessonsBackend.scaleFactor

                        // 宽度动画；特殊窗口引擎注入 suppressExpandAnim=true 抑制首次加载展开动画（主引擎无此属性，正常播放）
                        Behavior on width {
                            enabled: typeof suppressExpandAnim === "undefined" ? true : !suppressExpandAnim
                            NumberAnimation {
                                duration: 400
                                easing.type: Easing.OutCubic
                            }
                        }

                        // 更新目标宽度
                        function updateTargetWidth() {
                            var newWidth = expanded ? expandedWidth : foldedWidth
                            // 阈值设为0.1，确保微小变化也能触发动画
                            if (Math.abs(newWidth - targetWidth) > 0.1) {
                                targetWidth = newWidth
                            }
                        }

                        onExpandedChanged: updateTargetWidth()

                        Connections {
                            target: expanded ? lessonFullName : null
                            function onContentWidthChanged() { updateTargetWidth() }
                        }
                        Connections {
                            target: expanded ? remainingText : null
                            function onContentWidthChanged() { updateTargetWidth() }
                        }
                        Connections {
                            target: expanded ? lessonFullName : null
                            function onImplicitWidthChanged() { updateTargetWidth() }
                        }
                        Connections {
                            target: expanded ? remainingText : null
                            function onImplicitWidthChanged() { updateTargetWidth() }
                        }

                        Component.onCompleted: updateTargetWidth()

                        Rectangle {
                            x: 0
                            y: 0
                            width: parent.width
                            height: parent.height
                            radius: (lessonsBackend.mode === "normal" ? 20 : 23) * lessonsBackend.scaleFactor
                            color: {
                                if (isHighlighted) {
                                    if (lessonsBackend.mode === "normal") {
                                        return modelData.id === lessonsBackend.currentLessonId ? "#e98f83" : "#57c7a5"
                                    } else {
                                        return "transparent"
                                    }
                                }
                                return "transparent"
                            }
                            border.width: {
                                if (isHighlighted && lessonsBackend.mode !== "normal") {
                                    return 2 * lessonsBackend.scaleFactor
                                }
                                return 0
                            }
                            border.color: {
                                if (modelData.id === lessonsBackend.currentLessonId) {
                                    return "#e98f83"
                                } else if (lessonsBackend.currentState === 0 && modelData.id === lessonsBackend.nextLessonId) {
                                    return "#57c7a5"
                                }
                                return "transparent"
                            }
                        }

                        // 折叠时显示的缩写文本
                        Text {
                            id: lessonAbbr
                            visible: !expanded
                            anchors.centerIn: parent
                            text: modelData.abbr
                            font.pixelSize: 28 * lessonsBackend.scaleFactor
                            font.family: lessonsBackend.fontFamily
                            font.weight: lessonsBackend.fontWeight
                            color: {
                                if (isHighlighted) {
                                    if (lessonsBackend.mode === "normal") {
                                        return "#ffffff"
                                    } else {
                                        return effectiveDarkTheme ? "#ffffff" : "#000000"
                                    }
                                }
                                return effectiveDarkTheme ? "#ffffff" : "#000000"
                            }
                            Behavior on color {
                                ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
                            }
                        }

                        // 展开时显示的内容
                        Row {
                            visible: expanded
                            anchors.left: parent.left
                            anchors.leftMargin: 8 * lessonsBackend.scaleFactor
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 0

                            Icon {
                                id: iconItem
                                width: 30 * lessonsBackend.scaleFactor
                                height: parent.height
                                size: 30 * lessonsBackend.scaleFactor
                                icon: lessonsBackend.currentIcon
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                            }

                            Item { width: 8 * lessonsBackend.scaleFactor; height: 1 }

                            Text {
                                id: lessonFullName
                                text: modelData.fullName
                                font.pixelSize: 27 * lessonsBackend.scaleFactor
                                font.family: lessonsBackend.fontFamily
                                font.weight: lessonsBackend.fontWeight
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                                anchors.verticalCenter: parent.verticalCenter
                                Behavior on color {
                                    ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
                                }
                            }

                            Item {
                                id: separatorContainer
                                width: 22 * lessonsBackend.scaleFactor
                                height: parent.height
                                Rectangle {
                                    width: 2 * lessonsBackend.scaleFactor
                                    height: 28 * lessonsBackend.scaleFactor
                                    anchors.centerIn: parent
                                    gradient: Gradient {
                                        GradientStop { position: 0.0; color: "transparent" }
                                        GradientStop { position: 0.3; color: effectiveDarkTheme ? Qt.rgba(1,1,1,0.6) : Qt.rgba(0,0,0,0.4) }
                                        GradientStop { position: 0.7; color: effectiveDarkTheme ? Qt.rgba(1,1,1,0.6) : Qt.rgba(0,0,0,0.4) }
                                        GradientStop { position: 1.0; color: "transparent" }
                                    }
                                }
                            }

                            Text {
                                id: remainingText
                                text: lessonsBackend.currentRemainingText
                                // 倒计时样式：大字号(large)时与课程名称同字号（27），否则默认（18）
                                font.pixelSize: (lessonsBackend.countdownStyle === "large" ? 25 : 18) * lessonsBackend.scaleFactor
                                font.family: lessonsBackend.fontFamily
                                font.weight: lessonsBackend.fontWeight
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                                // 大字号时降低透明度：深色模式 75%，浅色模式 65%
                                opacity: lessonsBackend.countdownStyle === "large"
                                    ? (effectiveDarkTheme ? 0.8 : 0.7)
                                    : 1.0
                                verticalAlignment: Text.AlignVCenter
                                height: parent.height
                                Behavior on color {
                                    ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
                                }
                                Behavior on opacity {
                                    NumberAnimation { duration: 200; easing.type: Easing.OutCubic }
                                }
                                // 当内容宽度变化时，更新父项目标宽度
                                onContentWidthChanged: updateTargetWidth()
                                onImplicitWidthChanged: updateTargetWidth()
                            }
                        }
                    }
                }

                // 分隔符组件
                Component {
                    id: separatorComponent
                    Item {
                        width: 10 * lessonsBackend.scaleFactor
                        height: (lessonsBackend.mode === "normal" ? 40 : 46) * lessonsBackend.scaleFactor

                        Rectangle {
                            width: 2 * lessonsBackend.scaleFactor
                            height: 32 * lessonsBackend.scaleFactor
                            anchors.centerIn: parent
                            gradient: Gradient {
                                GradientStop { position: 0.0; color: "transparent" }
                                GradientStop { position: 0.4; color: effectiveDarkTheme ? Qt.rgba(1,1,1,0.7) : Qt.rgba(0,0,0,0.5) }
                                GradientStop { position: 0.6; color: effectiveDarkTheme ? Qt.rgba(1,1,1,0.7) : Qt.rgba(0,0,0,0.5) }
                                GradientStop { position: 1.0; color: "transparent" }
                            }
                        }
                    }
                }

                // 占位提示组件
                Component {
                    id: placeholderComponent
                    Item {
                        // 占位提示：固定 Icon 尺寸 + RowLayout AlignVCenter 显式垂直居中，缩放时位置稳定
                        width: contentRow.implicitWidth + 20 * lessonsBackend.scaleFactor
                        height: (lessonsBackend.mode === "normal" ? 40 : 46) * lessonsBackend.scaleFactor

                        RowLayout {
                            id: contentRow
                            anchors.centerIn: parent
                            spacing: 8 * lessonsBackend.scaleFactor

                            Icon {
                                Layout.preferredWidth: 24 * lessonsBackend.scaleFactor
                                Layout.preferredHeight: 24 * lessonsBackend.scaleFactor
                                Layout.alignment: Qt.AlignVCenter
                                size: 24 * lessonsBackend.scaleFactor
                                icon: modelData.icon
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                            }

                            Text {
                                id: placeholderText
                                text: modelData.text
                                font.pixelSize: 18 * lessonsBackend.scaleFactor
                                font.family: lessonsBackend.fontFamily
                                font.weight: lessonsBackend.fontWeight
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                                verticalAlignment: Text.AlignVCenter
                                Layout.alignment: Qt.AlignVCenter
                                Behavior on color {
                                    ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
                                }
                            }
                        }
                    }
                }
            }

            // 滚动条
            ScrollBar.horizontal: ScrollBar {
                id: hScrollBar
                policy: ScrollBar.AsNeeded
                visible: lessonsListView.contentWidth > lessonsListView.width && lessonsListView.scrollBarVisible

                onPressedChanged: {
                    if (pressed) {
                        lessonsListView.pauseAutoScroll()
                        lessonsListView.updateScrollBarVisible(true)
                    } else {
                        userInteractionTimer.restart()
                    }
                }
                onActiveChanged: {
                    if (active) {
                        lessonsListView.updateScrollBarVisible(true)
                    }
                }
            }

            // 从后端接收滚动请求
            Connections {
                target: lessonsBackend
                function onScrollRequested(index) {
                    if (lessonsListView.autoScrollEnabled && lessonsListView.contentWidth > lessonsListView.width) {
                        lessonsListView.scrollToIndex(index)
                    }
                }
            }

            // 用 itemAtIndex(index).x（displayMargin 保证全实例化，真实绝对位置）算目标 contentX：
            // 左 20%，末尾贴右缘 maxX，开头贴左缘 0；未实例化返回 NaN 让调用方跳过
            function computeTargetX(index) {
                forceLayout()
                var maxX = contentWidth - width
                if (maxX <= 0) return -1
                var it = itemAtIndex(index)
                if (!it) return NaN  // delegate 尚未实例化，布局未稳定
                var itemX = it.x     // 目标项在内容坐标系中的绝对位置
                var target = itemX - 0.2 * width
                if (target <= 0) return 0
                if (target >= maxX) return maxX
                return target
            }

            // 滚动到指定索引（左20%，平滑动画）：新目标用 computeTargetX，锁定目标位置防抖，动画结束后 finalizeScroll 精确对齐
            function scrollToIndex(index) {
                forceLayout()
                if (!autoScrollEnabled) return
                if (contentWidth <= width) {
                    // 内容放得下：contentX 归零居中（清除宽度变化瞬态残留偏移）
                    if (contentX !== 0) contentX = 0
                    return
                }
                // 防抖：动画中同一目标不打断（避免每秒请求反复 stop+start 导致抖动）
                if (scrollAnimating && lastScrollIndex === index) return
                if (lastScrollIndex === index && lastTargetX >= 0) {
                    // 同索引：已到位则不动；被手动滚动偏离则平滑动画滚回锁定目标
                    if (Math.abs(contentX - lastTargetX) < 2) return
                    scrollAnimation.to = lastTargetX
                    scrollAnimation.start()
                    return
                }
                // 新目标：用真实几何计算目标位置，交给动画平滑滚动
                var targetX = computeTargetX(index)
                if (isNaN(targetX)) {
                    // 布局未稳定：清空锁定跳过本次，等下一次请求重试
                    lastScrollIndex = -1
                    lastTargetX = -1
                    return
                }
                if (targetX < 0) {
                    lastScrollIndex = index
                    return
                }
                lastScrollIndex = index
                lastTargetX = targetX
                if (Math.abs(contentX - targetX) < 2) return
                if (scrollAnimation.running) scrollAnimation.stop()
                scrollAnimating = true
                scrollAnimation.to = targetX
                scrollAnimation.start()
            }

            // 动画结束后精确对齐：重算真实目标位置，修正动画中宽度变化导致的偏差
            function finalizeScroll() {
                if (lastScrollIndex < 0) return
                var targetX = computeTargetX(lastScrollIndex)
                if (isNaN(targetX)) return  // 布局未稳定：保持现状，等下一次重试
                if (targetX < 0) return
                if (Math.abs(contentX - targetX) > 1) {
                    contentX = targetX
                }
                lastTargetX = targetX
            }

            // 内部滚动到当前高亮课程
            function scrollToCurrentLesson() {
                var targetId = lessonsBackend.currentLessonId || lessonsBackend.nextLessonId
                if (!targetId) return
                var items = lessonsBackend.displayItems
                for (var i = 0; i < items.length; i++) {
                    if (items[i].type === "lesson" && items[i].id === targetId) {
                        scrollToIndex(i)
                        break
                    }
                }
            }

            // 滚动动画（供自动滚动和滚轮共用）
            NumberAnimation {
                id: scrollAnimation
                target: lessonsListView
                property: "contentX"
                duration: 400
                easing.type: Easing.OutCubic
                // 动画结束/停止时复位防抖标志，并精确对齐修正边界偏差
                onRunningChanged: {
                    if (!running) {
                        lessonsListView.scrollAnimating = false
                        lessonsListView.finalizeScroll()
                    }
                }
            }

            // 监听课程变化，立即滚动（如果允许）
            Connections {
                target: lessonsBackend
                function onCurrentLessonIdChanged() {
                    if (lessonsListView.autoScrollEnabled) lessonsListView.scrollToCurrentLesson()
                }
                function onNextLessonIdChanged() {
                    if (lessonsListView.autoScrollEnabled) lessonsListView.scrollToCurrentLesson()
                }
                function onLessonsUpdated() {
                    // 不重置锁定：高亮变化自然以新索引重新定位，避免频繁重置闪现
                    if (lessonsListView.autoScrollEnabled) lessonsListView.scrollToCurrentLesson()
                }
            }
        }
        // ========== 课程列表结束 ==========

        // 右侧居中空白：内容放得下时把列表夹在中间；放不下时宽度为 0，列表占满剩余空间
        Item {
            id: rightSpacer
            height: parent.height
            width: centerSpacerWidth()
        }

        // 右侧按钮区前 8px 间距（平板与投影均保留：分别衔接手写板胶囊 / 白板切换钮）
        Item { width: 8 * lessonsBackend.scaleFactor; height: parent.height; visible: root.showTopButtons }

        // 按钮1：白板模式/切换（仅投影设备或其他显示）
        RoundButton {
            id: button1
            objectName: "topButton1"
            visible: root.showTopButtons && !root.isInteractivePanel
            enabled: !lessonsBackend.switching  // 窗口切换期间禁用，防止误操作
            hoverEnabled: true  // 使 hovered 生效，用于文本提示
            implicitWidth: 30 * lessonsBackend.scaleFactor
            implicitHeight: 30 * lessonsBackend.scaleFactor
            icon.name: {
                if (lessonsBackend.mode === "whiteboard") return "ic_fluent_weather_moon_20_regular"
                if (lessonsBackend.mode === "blackboard") return "ic_fluent_weather_sunny_20_regular"
                return "ic_fluent_weather_sunny_20_regular" // 正常模式为白板模式
            }
            icon.width: 18 * lessonsBackend.scaleFactor
            icon.height: 18 * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
            onClicked: {
                if (lessonsBackend.mode === "normal") {
                    lessonsBackend.enterWhiteboard()
                } else if (lessonsBackend.mode === "whiteboard") {
                    lessonsBackend.enterBlackboard()
                } else if (lessonsBackend.mode === "blackboard") {
                    lessonsBackend.enterWhiteboard()
                }
            }
        }

        Item { width: 10 * lessonsBackend.scaleFactor; height: parent.height; visible: root.showTopButtons && !root.isInteractivePanel }

        // 按钮2：熄屏模式/退出
        RoundButton {
            id: button2
            objectName: "topButton2"
            visible: root.showTopButtons && !root.isInteractivePanel
            enabled: !lessonsBackend.switching  // 窗口切换期间禁用，防止误操作
            hoverEnabled: true  // 使 hovered 生效，用于文本提示
            implicitWidth: 30 * lessonsBackend.scaleFactor
            implicitHeight: 30 * lessonsBackend.scaleFactor
            icon.name: {
                if (lessonsBackend.mode !== "normal") return "ic_fluent_arrow_exit_20_regular"
                return "ic_fluent_weather_moon_20_regular" // 正常模式为熄屏模式
            }
            icon.width: 18 * lessonsBackend.scaleFactor
            icon.height: 18 * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
            onClicked: {
                if (lessonsBackend.mode === "normal") {
                    lessonsBackend.enterBlackboard()
                } else {
                    lessonsBackend.exitSpecialMode()
                }
            }
        }

        // 手写板模式胶囊按钮（仅交互智能平板正常模式）：外壳尽量还原 RinUI RoundButton 样式
        // （常态 controlQuaternary、悬停 controlSecondary、按下 controlTertiary+0.7、禁用 controlColor+0.65、
        // 1px controlBorderColor 边框 + 胶囊圆角）；前景文字/图标用与顶栏一致的纯黑/白保持清晰（不灰）。
        // 文字直接显示设置对应模式（黑板模式/白板模式，随 specialModeAction 自动刷新），点击进入该模式。
        Item {
            id: handboardButton
            objectName: "topHandboardButton"
            visible: root.showTopButtons && root.isInteractivePanel
            enabled: !lessonsBackend.switching  // 窗口切换期间禁用，防止误操作
            anchors.verticalCenter: parent.verticalCenter

            // 内容前景色：与顶栏文字/图标一致（深色白、浅色黑），避免主题近黑灰显得发灰
            readonly property color fgColor: effectiveDarkTheme ? "#ffffff" : "#000000"
            // 当前设置将打开的模式
            readonly property string actionMode: settingsBackend.specialModeAction === "whiteboard" ? "whiteboard" : "blackboard"
            // 左右内边距（较 RinUI Button 默认 implicitWidth=row+26 略收紧，视觉更紧凑）
            readonly property real padX: 10 * lessonsBackend.scaleFactor
            // 高度较顶部圆形按钮（30）略高，使平板“xx模式”胶囊按钮更有辨识度
            implicitHeight: 34 * lessonsBackend.scaleFactor
            implicitWidth: hbRow.implicitWidth + 2 * padX
            // 状态透明度仿 RinUI Button：禁用 0.65、按下 0.7、其余 1
            opacity: !enabled ? 0.65 : (hbArea.pressed ? 0.7 : 1)
            Behavior on opacity { NumberAnimation { duration: 120 } }

            // 胶囊背景：主题色还原 RinUI RoundButton（非 flat）——常态/悬停/按下/禁用各取对应主题色
            Rectangle {
                id: handboardBg
                anchors.fill: parent
                radius: height / 2
                border.width: Theme.currentTheme.appearance.borderWidth
                border.color: Theme.currentTheme.colors.controlBorderColor
                color: !handboardButton.enabled
                    ? Theme.currentTheme.colors.controlColor
                    : (hbArea.pressed
                        ? Theme.currentTheme.colors.controlTertiaryColor
                        : (hbArea.containsMouse
                            ? Theme.currentTheme.colors.controlSecondaryColor
                            : Theme.currentTheme.colors.controlQuaternaryColor))
                Behavior on color { ColorAnimation { duration: Utils.appearanceSpeed; easing.type: Easing.OutQuart } }
            }

            // 内容：图标 + 模式文字（图标-文字间距略小于 RinUI Button row spacing 8）
            Row {
                id: hbRow
                anchors.centerIn: parent
                spacing: 6 * lessonsBackend.scaleFactor
                Icon {
                    id: hbIcon
                    width: 18 * lessonsBackend.scaleFactor
                    height: 18 * lessonsBackend.scaleFactor
                    size: 18 * lessonsBackend.scaleFactor
                    icon: "ic_fluent_whiteboard_20_regular"
                    color: handboardButton.fgColor
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    id: hbText
                    text: handboardButton.actionMode === "whiteboard" ? qsTr("白板模式") : qsTr("黑板模式")
                    font.pixelSize: 13 * lessonsBackend.scaleFactor
                    font.family: lessonsBackend.fontFamily
                    font.weight: Font.Normal  // 不加粗（不随 lessonsBackend.fontWeight）
                    color: handboardButton.fgColor
                    verticalAlignment: Text.AlignVCenter
                    anchors.verticalCenter: parent.verticalCenter
                }
            }

            MouseArea {
                id: hbArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: lessonsBackend.enterHandboardMode()
            }
        }

        // 尾部留白：平板时=按钮与胶囊上下间距一致（(胶囊高-按钮高)/2，比 13px 更小更贴合）；
        // 投影设备保持 13px（无需调整）
        Item {
            width: root.isInteractivePanel
                ? Math.max(0, (root.height - handboardButton.implicitHeight) / 2)
                : 13 * lessonsBackend.scaleFactor
            height: parent.height
        }
    }

    // ===== 悬停渐隐：非按钮区拦截层 =====
    // 覆盖"换课按钮右缘(13+30+8=51px) 至 右侧操作按钮带起点"之间的整段（课程列表 + 两侧留白），
    // 即列表可用宽 availableListViewWidth()。开启时吞掉该区域全部鼠标/滚轮事件
    // （课程列表不再接受鼠标事件——不滚动/不拖动/不弹菜单）；按钮带（左右两端）不在本层范围内，
    // 鼠标在其上不渐隐、按钮正常可点有 hover。
    MouseArea {
        id: fadeBlock
        visible: root.hoverFadeActive
        enabled: root.hoverFadeActive
        z: 5
        x: (13 + 30 + 8) * lessonsBackend.scaleFactor
        y: 0
        width: availableListViewWidth()
        height: root.height
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        cursorShape: Qt.ArrowCursor
        onPressed: (mouse) => { mouse.accepted = true }
        onReleased: (mouse) => { mouse.accepted = true }
        onClicked: (mouse) => { mouse.accepted = true }
        onDoubleClicked: (mouse) => { mouse.accepted = true }
        onWheel: (wheel) => { wheel.accepted = true }
    }

    // ===== 按钮文本提示（tooltip）=====
    // 悬停按钮显示，x 居中于按钮、y 在胶囊下边框 5px；显示/隐藏 150ms 渐变。
    // 一般模式带 mask：显示时移除、隐藏淡出后恢复（引用计数避免与右键菜单冲突）。
    Rectangle {
        id: tooltip0
        width: tip0Text.implicitWidth + 18
        height: 30
        radius: 6
        border.width: 1
        color: effectiveDarkTheme ? "#2c2c2c" : "#F9F9F9"
        border.color: effectiveDarkTheme ? Qt.rgba(1, 1, 1, 0.2) : Qt.rgba(0, 0, 0, 0.0578)
        x: switchButton.x + switchButton.width / 2 - width / 2
        y: root.height + 5
        z: 10
        opacity: switchButton.hovered ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }
        property bool maskActive: false
        onVisibleChanged: {
            if (visible && !maskActive) {
                lessonsBackend.hideWidgetMask()
                maskActive = true
            } else if (!visible && maskActive) {
                fadeOutTimer0.start()
            }
        }
        Timer {
            id: fadeOutTimer0
            interval: 160
            onTriggered: {
                if (tooltip0.maskActive && !tooltip0.visible) {
                    lessonsBackend.showWidgetMask()
                    tooltip0.maskActive = false
                }
            }
        }
        Text {
            id: tip0Text
            anchors.centerIn: parent
            text: qsTr("换课")
            font.pixelSize: 12 * lessonsBackend.scaleFactor
            font.family: Qt.application.font.family
            color: effectiveDarkTheme ? "#ffffff" : "#000000"
        }
    }

    Rectangle {
        id: tooltip1
        width: tip1Text.implicitWidth + 18
        height: 30
        radius: 6
        border.width: 1
        color: effectiveDarkTheme ? "#2c2c2c" : "#F9F9F9"
        border.color: effectiveDarkTheme ? Qt.rgba(1, 1, 1, 0.2) : Qt.rgba(0, 0, 0, 0.0578)
        x: button1.x + button1.width / 2 - width / 2
        y: root.height + 5
        z: 10
        opacity: button1.hovered ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }
        property bool maskActive: false
        onVisibleChanged: {
            if (visible && !maskActive) {
                lessonsBackend.hideWidgetMask()
                maskActive = true
            } else if (!visible && maskActive) {
                fadeOutTimer1.start()
            }
        }
        Timer {
            id: fadeOutTimer1
            interval: 160
            onTriggered: {
                if (tooltip1.maskActive && !tooltip1.visible) {
                    lessonsBackend.showWidgetMask()
                    tooltip1.maskActive = false
                }
            }
        }
        Text {
            id: tip1Text
            anchors.centerIn: parent
            text: lessonsBackend.mode === "whiteboard" ? qsTr("熄屏模式") : qsTr("白板模式")
            font.pixelSize: 12 * lessonsBackend.scaleFactor
            font.family: Qt.application.font.family  // 提示文字用系统字体
            color: effectiveDarkTheme ? "#ffffff" : "#000000"
        }
    }

    Rectangle {
        id: tooltip2
        width: tip2Text.implicitWidth + 18
        height: 30
        radius: 6
        border.width: 1
        color: effectiveDarkTheme ? "#2c2c2c" : "#F9F9F9"
        border.color: effectiveDarkTheme ? Qt.rgba(1, 1, 1, 0.2) : Qt.rgba(0, 0, 0, 0.0578)
        x: button2.x + button2.width / 2 - width / 2
        y: root.height + 5
        z: 10
        opacity: button2.hovered ? 1 : 0
        visible: opacity > 0.01
        Behavior on opacity {
            NumberAnimation { duration: 150; easing.type: Easing.OutCubic }
        }
        property bool maskActive: false
        onVisibleChanged: {
            if (visible && !maskActive) {
                lessonsBackend.hideWidgetMask()
                maskActive = true
            } else if (!visible && maskActive) {
                fadeOutTimer2.start()
            }
        }
        Timer {
            id: fadeOutTimer2
            interval: 160
            onTriggered: {
                if (tooltip2.maskActive && !tooltip2.visible) {
                    lessonsBackend.showWidgetMask()
                    tooltip2.maskActive = false
                }
            }
        }
        Text {
            id: tip2Text
            anchors.centerIn: parent
            text: lessonsBackend.mode === "normal" ? qsTr("熄屏模式") : qsTr("退出")
            font.pixelSize: 12 * lessonsBackend.scaleFactor
            font.family: Qt.application.font.family  // 提示文字用系统字体
            color: effectiveDarkTheme ? "#ffffff" : "#000000"
        }
    }

    // 列表可用宽度（固定：总宽减去两侧固定元素，不依赖 ListView 自身 contentWidth）
    // 特殊模式 + 交互智能平板时顶部按钮隐藏（showTopButtons=false），按钮不占位，
    // 固定宽度只计左右边距（13+13）；否则按设备形态计右侧按钮占用：
    // 投影设备=白板/熄屏双按钮；交互智能平板=单个"手写板模式"胶囊（宽度随内容，取按钮实际宽）。
    function availableListViewWidth() {
        var s = lessonsBackend.scaleFactor
        if (!root.showTopButtons) {
            return root.width - (13 + 13) * s
        }
        if (root.isInteractivePanel) {
            // 左：13 边距 + 换课 30 + 8；右：8 间距 + 胶囊按钮实际宽 + 尾部留白
            //（尾部留白 = 按钮与胶囊上下间距一致 = (胶囊高-按钮高)/2，随按钮高度自动）
            var tailPad = Math.max(0, (root.height - handboardButton.implicitHeight) / 2)
            return root.width - (13 + 30 + 8) * s - (8 * s + tailPad) - handboardButton.width
        }
        // 投影设备：左=13+换课30+8；右=8+按钮1 30+12+按钮2 30+13
        return root.width - (13 + 30 + 8 + 8 + 30 + 12 + 30 + 13) * s
    }

    // 居中 spacer 宽度：内容较窄时左右各占剩余一半使列表居中；超出时返回 0 让列表占满并可滚动
    function centerSpacerWidth() {
        var aw = availableListViewWidth()
        var cw = lessonsListView.contentWidth
        if (cw <= 0) {
            return 0
        }
        return Math.max(0, (aw - cw) / 2)
    }
}