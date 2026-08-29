import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
import RinUI

Item {
    id: root
    height: 54 * lessonsBackend.scaleFactor

    // 根据模式计算实际暗色主题
    readonly property bool effectiveDarkTheme: {
        if (lessonsBackend.mode === "whiteboard") return false
        if (lessonsBackend.mode === "blackboard") return true
        return lessonsBackend.isDarkTheme
    }

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

        // 换课按钮（禁用）
        RoundButton {
            id: switchButton
            enabled: false
            implicitWidth: 30 * lessonsBackend.scaleFactor
            implicitHeight: 30 * lessonsBackend.scaleFactor
            icon.name: "ic_fluent_arrow_swap_20_regular"
            icon.width: 18 * lessonsBackend.scaleFactor
            icon.height: 18 * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
        }

        Item { width: 16 * lessonsBackend.scaleFactor; height: parent.height }

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
            // 视口宽度 = 可用宽度 - 两侧 spacer：内容放得下时 ListView 与内容同宽并被
            // 两侧 spacer 夹住居中（contentX 恒为 0）；放不下时 spacer=0，视口占满
            // 剩余空间，自动滚动/滚动动画等逻辑正常执行。
            // 注意：不覆盖 contentWidth，用 ListView 自动计算的真实内容宽度（固定宽 delegate，
            // 与视口宽度无关，无循环绑定）。
            width: availableListViewWidth() - leftSpacer.width - rightSpacer.width

            // 模型改为 displayItems，包含课程和分隔符
            model: lessonsBackend.displayItems

            // 预实例化视口外的 delegate，保证 itemAtIndex(index) 对任意 index 都能
            // 返回真实几何（否则远处 delegate 未实例化：itemAtIndex 返回 null，
            // positionViewAtIndex 用估算返回错误 contentX，滚到错误位置/滚过头回弹）。
            // 课程列表项数有限（通常 < 30），全实例化开销可忽略。
            displayMarginBeginning: 10000
            displayMarginEnd: 10000

            // 自动滚动相关属性
            property bool autoScrollEnabled: true
            property bool userInteracted: false
            property bool hovered: false
            property bool scrollBarVisible: false
            // 自动滚动防抖：上次滚动目标索引/位置、是否动画进行中。
            // 防止同一目标被每秒滚动请求反复打断/重启动画（动画永远无法完成，
            // contentX 原地抖动=抽搐，高亮到不了左20%）。
            property int lastScrollIndex: -1
            property real lastTargetX: -1
            property bool scrollAnimating: false

            // 视图宽度 / 内容宽度变化 → 目标“左 20%”位置会变，重置锁定让下次
            // 滚动重新权威定位（避免沿用旧位置导致高亮不在左 20% / 露出空白）。
            // 宽度变化（尤其从“放得下”缩到“放不下”）的瞬态里，ListView 虚拟化
            // 布局尚未完成，delegate 可能未实例化（itemAtIndex 返回 null），立刻
            // 滚动会滚到错误位置。故清空锁定，并用 Qt.callLater 延迟到布局稳定后
            // 再权威定位，保证一次到位。
            // 同时：UI 宽度更新（特殊模式切换 / 主程序宽度跟随，uiLoader 宽度有
            // 400ms 平滑动画）期间视口宽度连续变化，滚动条会闪动；未悬停则直接
            // 暂时隐藏滚动条，等宽度稳定后再由 hover/交互重新显示。
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

            // 宽度/内容宽度变化后延迟重定位：放得下则 contentX 归零（居中），
            // 放不下则重新滚动到当前高亮课程。
            function relayoutScroll() {
                if (contentWidth <= width) {
                    if (contentX !== 0) contentX = 0
                } else if (autoScrollEnabled) {
                    scrollToCurrentLesson()
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
                // 用户操作列表滚动（拖拽/滚动条/滚轮）后，延迟 4 秒再恢复自动滚动。
                // 统一重启恢复定时器，确保一定在 4 秒后恢复（避免某路径遗漏 restart
                // 而永久卡死）。
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
                // 用户拖拽开始：立即停止自动滚动动画，避免与用户操作抢 contentX
                // （否则用户刚滚到的位置会被自动滚动动画拉走/打断）。
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
                // 暴露自身在模型中的 index，便于 computeTargetX 通过 contentItem 子项
                // 定位目标项的真实几何（也便于测试/调试）。
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

                        // 使用 Behavior 为宽度添加动画。
                        // 特殊窗口引擎在创建时注入 suppressExpandAnim=true（仅新窗口可见），
                        // 用于抑制首次加载的展开动画（新窗口直接以展开状态显示，避免与旧
                        // 窗口正在播放的展开动画重复）；主引擎无此属性，动画正常播放。
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
                        // 占位提示：用 RowLayout + AlignVCenter 可靠垂直居中。
                        // 原实现把 Icon 高度绑到父行高（height: parent.height）且行内默认顶部
                        // 对齐，缩放动画期间行高/文字高度更新节奏不一致，会导致文字提示位置
                        // 偏移（偏上/偏下）。这里固定 Icon 尺寸并显式垂直居中，缩放时位置稳定。
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

            // 用 itemAtIndex(index).x 计算目标 contentX：displayMargin 保证 delegate
            // 全实例化，x 为真实绝对位置。不依赖 positionViewAtIndex——它对 Loader+
            // 内容自适应宽度的远处/末尾项会返回错误 contentX（超过 maxX 或负数），
            // 导致滚过头回弹。返回目标项应位于的 contentX：左 20%；末尾项贴右缘
            // （maxX）；开头项贴左缘（0）。目标项未实例化（布局未稳定）返回 NaN，
            // 让调用方跳过本次滚动、延迟重试。
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

            // 滚动到指定索引（左20%位置，平滑动画）。
            // 新目标**一律**用 computeTargetX（itemAtIndex 真实几何，正确处理边界），
            // 恢复原位后动画到目标位置；锁定目标位置，同索引每秒请求沿用锁定值
            // （不重算、不跳变）；动画结束后由 finalizeScroll 精确对齐，修正滚过头/
            // 没滚到头的偏差。
            function scrollToIndex(index) {
                forceLayout()
                if (!autoScrollEnabled) return
                if (contentWidth <= width) {
                    // 内容放得下：居中显示，contentX 恒为 0（清除宽度变化瞬态
                    // 可能残留的滚动偏移，避免课程整体偏左、右侧露空白）。
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
                    // 布局未稳定：清空锁定并跳过本次，绝不滚到错误位置；
                    // 等 Qt.callLater / 下一次每秒请求重试。
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

            // 动画结束后精确对齐：重新用 itemAtIndex 真实几何计算目标位置，
            // 修正动画过程中视图宽度/内容宽度变化导致的滚过头/没滚到头的偏差。
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
                    // 不重置锁定：高亮课程变化会自然以新索引触发重新定位；
                    // 若每次课程数据更新都重置，会频繁重新定位导致闪现。
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

        Item { width: 16 * lessonsBackend.scaleFactor; height: parent.height }

        // 按钮1：白板模式/切换
        RoundButton {
            id: button1
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

        Item { width: 12 * lessonsBackend.scaleFactor; height: parent.height }

        // 按钮2：熄屏模式/退出
        RoundButton {
            id: button2
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

        Item { width: 13 * lessonsBackend.scaleFactor; height: parent.height }
    }

    // ===== 按钮文本提示（tooltip）=====
    // 悬停按钮时（无延迟）显示；圆角 6px、高度 30、左右边距 9；x 居中于对应按钮，
    // y 顶部距胶囊下边框 5px。显示/隐藏均有 150ms 透明度渐变动画。
    // 一般模式下窗口带 mask：显示时立即通知后端移除（不遮挡），隐藏时等淡出动画
    // 结束后再恢复 mask（引用计数避免与右键菜单冲突）。
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
            font.family: lessonsBackend.fontFamily
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
            font.family: lessonsBackend.fontFamily
            color: effectiveDarkTheme ? "#ffffff" : "#000000"
        }
    }

    // 列表可用宽度（固定：总宽减去两侧固定元素，不依赖 ListView 自身 contentWidth）
    function availableListViewWidth() {
        var fixedWidth = (13 + 30 + 16 + 16 + 30 + 12 + 30 + 13) * lessonsBackend.scaleFactor
        return root.width - fixedWidth
    }

    // 居中 spacer 宽度：内容比可用宽度窄时，左右各占剩余一半
    // （spacer + 列表内容 + spacer = 可用宽度，列表内容真正居中）；
    // 内容超出可用宽度时返回 0，让 ListView 占满剩余空间并正常滚动/自动滚动。
    // 声明式绑定使左右 spacer 与 ListView 宽度在 contentWidth / 窗口宽度变化时自动更新。
    function centerSpacerWidth() {
        var aw = availableListViewWidth()
        var cw = lessonsListView.contentWidth
        if (cw <= 0) {
            return 0
        }
        return Math.max(0, (aw - cw) / 2)
    }
}