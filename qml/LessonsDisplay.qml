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
            highlighted: effectiveDarkTheme
            primaryColor: effectiveDarkTheme ? "#444" : undefined
        }

        Item { width: 16 * lessonsBackend.scaleFactor; height: parent.height }

        // 左侧弹性空白
        Item {
            id: leftSpacer
            height: parent.height
            width: calculateSpacerWidth()
        }

        // ========== 课程列表 ==========
        ListView {
            id: lessonsListView
            orientation: ListView.Horizontal
            spacing: 5 * lessonsBackend.scaleFactor
            clip: true
            height: (lessonsBackend.mode === "normal" ? 40 : 46) * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
            width: calculateListViewWidth()
            contentWidth: childrenRect.width

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
                                font.pixelSize: 16 * lessonsBackend.scaleFactor
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
                                font.pixelSize: 16 * lessonsBackend.scaleFactor
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

        // 右侧弹性空白
        Item {
            id: rightSpacer
            height: parent.height
            width: calculateSpacerWidth()
        }

        Item { width: 16 * lessonsBackend.scaleFactor; height: parent.height }

        // 按钮1：白板模式/切换
        RoundButton {
            id: button1
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
            highlighted: effectiveDarkTheme
            primaryColor: effectiveDarkTheme ? "#444" : undefined
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
            implicitWidth: 30 * lessonsBackend.scaleFactor
            implicitHeight: 30 * lessonsBackend.scaleFactor
            icon.name: {
                if (lessonsBackend.mode !== "normal") return "ic_fluent_arrow_exit_20_regular"
                return "ic_fluent_weather_moon_20_regular" // 正常模式为熄屏模式
            }
            icon.width: 18 * lessonsBackend.scaleFactor
            icon.height: 18 * lessonsBackend.scaleFactor
            anchors.verticalCenter: parent.verticalCenter
            highlighted: effectiveDarkTheme
            primaryColor: effectiveDarkTheme ? "#444" : undefined
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

    // 计算列表视图宽度（限制为内容宽度或可用宽度的较小值）
    function calculateListViewWidth() {
        var fixedWidth = (13 + 30 + 16 + 16 + 30 + 12 + 30 + 13) * lessonsBackend.scaleFactor
        var availableWidth = root.width - fixedWidth
        var contentWidth = lessonsListView.contentWidth
        return Math.min(contentWidth, availableWidth)
    }

    // 计算空白宽度（左右相等）
    function calculateSpacerWidth() {
        var fixedWidth = (13 + 30 + 16 + 16 + 30 + 12 + 30 + 13) * lessonsBackend.scaleFactor
        var availableWidth = root.width - fixedWidth
        var listWidth = calculateListViewWidth()
        return Math.max(0, (availableWidth - listWidth) / 2)
    }

    // 当内容或尺寸变化时更新布局，并确保滚动位置不越界
    Connections {
        target: lessonsBackend
        function onLessonsUpdated() {
            leftSpacer.width = Qt.binding(calculateSpacerWidth)
            rightSpacer.width = Qt.binding(calculateSpacerWidth)
            lessonsListView.width = Qt.binding(calculateListViewWidth)
            Qt.callLater(function() {
                var maxX = Math.max(0, lessonsListView.contentWidth - lessonsListView.width)
                if (lessonsListView.contentX > maxX) {
                    lessonsListView.contentX = maxX
                }
            })
        }
    }

    // 初始绑定
    Component.onCompleted: {
        leftSpacer.width = Qt.binding(calculateSpacerWidth)
        rightSpacer.width = Qt.binding(calculateSpacerWidth)
        lessonsListView.width = Qt.binding(calculateListViewWidth)
    }
}