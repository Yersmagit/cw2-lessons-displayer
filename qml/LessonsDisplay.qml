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
    readonly property real radius: 27 * lessonsBackend.scaleFactor

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

            // 自动滚动相关属性
            property bool autoScrollEnabled: true
            property bool userInteracted: false
            property bool hovered: false
            property bool scrollBarVisible: false

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

                        // 使用 Behavior 为宽度添加动画
                        Behavior on width {
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
                                font.pixelSize: 18 * lessonsBackend.scaleFactor
                                font.family: lessonsBackend.fontFamily
                                font.weight: lessonsBackend.fontWeight
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                                verticalAlignment: Text.AlignVCenter
                                height: parent.height
                                Behavior on color {
                                    ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
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
                        property real textWidth: placeholderText.contentWidth
                        property real iconWidth: 24 * lessonsBackend.scaleFactor
                        width: iconWidth + 8 * lessonsBackend.scaleFactor + textWidth + 20 * lessonsBackend.scaleFactor
                        height: (lessonsBackend.mode === "normal" ? 40 : 46) * lessonsBackend.scaleFactor

                        Row {
                            anchors.centerIn: parent
                            spacing: 8 * lessonsBackend.scaleFactor

                            Icon {
                                width: 24 * lessonsBackend.scaleFactor
                                height: parent.height
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

            // 滚动到指定索引（左20%位置，带动画）
            function scrollToIndex(index) {
                forceLayout()
                if (!autoScrollEnabled) return
                if (contentWidth <= width) return
                var item = itemAtIndex(index)
                if (!item) return
                var targetX = item.x - width * 0.2
                targetX = Math.max(0, Math.min(targetX, contentWidth - width))
                if (Math.abs(contentX - targetX) < 1) return
                if (scrollAnimation.running) scrollAnimation.stop()
                scrollAnimation.to = targetX
                scrollAnimation.start()
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