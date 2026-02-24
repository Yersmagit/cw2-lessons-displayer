import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
import RinUI

Item {
    id: root
    height: 54

    // 背景颜色（带透明度，仿 Widget.qml）
    readonly property color bgColor: lessonsBackend.isDarkTheme
        ? Qt.rgba(30/255, 29/255, 34/255, 0.65)   // #1E1D22 半透明
        : Qt.rgba(251/255, 250/255, 255/255, 0.7) // #FBFAFF 半透明

    // 边框基础颜色（用于渐变）
    readonly property color borderBaseColor: lessonsBackend.isDarkTheme
        ? Qt.rgba(255/255, 255/255, 255/255, 0.4)
        : Qt.rgba(255/255, 255/255, 255/255, 1)

    readonly property real borderWidth: 1.5
    readonly property real radius: 27

    // 背景矩形（纯色，无边框）
    Rectangle {
        id: backgroundRect
        anchors.fill: parent
        radius: root.radius
        color: bgColor
    }

    // 渐变边框层
    Item {
        anchors.fill: parent
        z: 1

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

        opacity: 0.85
    }

    // 内容容器（手动布局）
    Row {
        id: contentRow
        anchors.fill: parent
        spacing: 0

        // 左侧固定边距
        Item { width: 13; height: parent.height }

        // 换课按钮（禁用）
        RoundButton {
            id: switchButton
            enabled: false
            implicitWidth: 30
            implicitHeight: 30
            icon.name: "ic_fluent_arrow_swap_20_regular"
            anchors.verticalCenter: parent.verticalCenter
            highlighted: lessonsBackend.isDarkTheme
            primaryColor: lessonsBackend.isDarkTheme ? "#444" : undefined
        }

        Item { width: 16; height: parent.height }

        // 左侧弹性空白
        Item {
            id: leftSpacer
            height: parent.height
            width: calculateSpacerWidth()
        }

        // 课程列表（支持自动滚动和用户交互暂停）
        ListView {
            id: lessonsListView
            orientation: ListView.Horizontal
            spacing: 5
            clip: true
            height: 40
            anchors.verticalCenter: parent.verticalCenter
            width: calculateListViewWidth()
            contentWidth: childrenRect.width

            // 自动滚动相关属性
            property bool autoScrollEnabled: true
            property bool userInteracted: false

            // 用户交互后延迟恢复定时器（4000ms）
            Timer {
                id: userInteractionTimer
                interval: 4000
                onTriggered: {
                    lessonsListView.autoScrollEnabled = true
                    lessonsListView.userInteracted = false
                    // 触发一次滚动，因为可能错过了几次
                    if (lessonsListView.contentWidth > lessonsListView.width) {
                        lessonsListView.scrollToCurrentLesson()
                    }
                }
            }

            // 检测用户滚动开始
            onMovementStarted: {
                autoScrollEnabled = false
                userInteracted = true
                userInteractionTimer.restart()
            }

            // 鼠标区域：处理滚轮事件（带动画）
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.NoButton
                propagateComposedEvents: true
                onWheel: (wheel) => {
                    // 用户滚轮交互
                    lessonsListView.autoScrollEnabled = false
                    lessonsListView.userInteracted = true
                    userInteractionTimer.restart()

                    // 仅当内容宽度超出视图时才处理滚轮
                    if (wheel.angleDelta.y !== 0 && lessonsListView.contentWidth > lessonsListView.width) {
                        // 步长：向上滚（负delta）向左移动，向下滚向右移动
                        var step = wheel.angleDelta.y > 0 ? -150 : 150
                        var targetX = lessonsListView.contentX + step
                        // 边界限制
                        targetX = Math.max(0, Math.min(targetX, lessonsListView.contentWidth - lessonsListView.width))
                        // 如果目标位置与当前相差很小，忽略
                        if (Math.abs(targetX - lessonsListView.contentX) < 1) return
                        // 停止当前动画
                        if (scrollAnimation.running) scrollAnimation.stop()
                        scrollAnimation.to = targetX
                        scrollAnimation.start()
                        wheel.accepted = true
                    }
                }
            }

            model: lessonsBackend.lessons
            delegate: Item {
                width: childrenRect.width + 10
                height: 40

                Rectangle {
                    anchors.fill: parent
                    radius: 20
                    color: {
                        if (modelData.id === lessonsBackend.currentLessonId) {
                            // 上课时高亮当前课程（红色）
                            return "#e98f83"
                        } else if (lessonsBackend.currentState === 0 && modelData.id === lessonsBackend.nextLessonId) {
                            // 课间时高亮下一节课（绿色）
                            return "#57c7a5"
                        }
                        return "transparent"
                    }
                }

                Text {
                    anchors.centerIn: parent
                    text: modelData.abbr
                    font.pixelSize: 28
                    font.bold: true
                    color: {
                        if (modelData.id === lessonsBackend.currentLessonId ||
                            (lessonsBackend.currentState === 0 && modelData.id === lessonsBackend.nextLessonId)) {
                            return "#ffffff"
                        }
                        return lessonsBackend.isDarkTheme ? "#ffffff" : "#000000"
                    }
                }
            }

            // 滚动条，按需显示
            ScrollBar.horizontal: ScrollBar {
                policy: ScrollBar.AsNeeded
                visible: lessonsListView.contentWidth > lessonsListView.width
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

            // 滚动到指定索引（靠左对齐，带动画）
            function scrollToIndex(index) {
                if (!autoScrollEnabled) return
                if (contentWidth <= width) return
                var item = itemAtIndex(index)
                if (!item) return
                var targetX = item.x
                // 边界限制：不能小于0，不能大于 contentWidth - width
                targetX = Math.max(0, Math.min(targetX, contentWidth - width))
                // 如果已经接近目标，跳过动画
                if (Math.abs(contentX - targetX) < 1) return
                // 停止当前动画
                if (scrollAnimation.running) scrollAnimation.stop()
                scrollAnimation.to = targetX
                scrollAnimation.start()
            }

            // 内部滚动到当前高亮课程
            function scrollToCurrentLesson() {
                var targetId = lessonsBackend.currentLessonId || lessonsBackend.nextLessonId
                if (!targetId) return
                for (var i = 0; i < model.count; i++) {
                    if (model[i].id === targetId) {
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

        // 右侧弹性空白
        Item {
            id: rightSpacer
            height: parent.height
            width: calculateSpacerWidth()
        }

        Item { width: 16; height: parent.height }

        // 白板模式按钮
        RoundButton {
            id: lightButton
            implicitWidth: 30
            implicitHeight: 30
            enabled: false
            icon.name: "ic_fluent_weather_sunny_20_regular"
            anchors.verticalCenter: parent.verticalCenter
            highlighted: lessonsBackend.isDarkTheme
            primaryColor: lessonsBackend.isDarkTheme ? "#444" : undefined
            onClicked: console.log("Light mode clicked")
        }

        Item { width: 12; height: parent.height }

        // 熄屏模式按钮
        RoundButton {
            id: darkButton
            implicitWidth: 30
            implicitHeight: 30
            enabled: false
            icon.name: "ic_fluent_weather_moon_20_regular"
            anchors.verticalCenter: parent.verticalCenter
            highlighted: lessonsBackend.isDarkTheme
            primaryColor: lessonsBackend.isDarkTheme ? "#444" : undefined
            onClicked: console.log("Dark mode clicked")
        }

        Item { width: 13; height: parent.height }
    }

    // 计算列表视图宽度（限制为内容宽度或可用宽度的较小值）
    function calculateListViewWidth() {
        var fixedWidth = 13 + 30 + 16 + 16 + 30 + 12 + 30 + 13
        var availableWidth = root.width - fixedWidth
        var contentWidth = lessonsListView.contentWidth
        return Math.min(contentWidth, availableWidth)
    }

    // 计算空白宽度（左右相等）
    function calculateSpacerWidth() {
        var fixedWidth = 13 + 30 + 16 + 16 + 30 + 12 + 30 + 13
        var availableWidth = root.width - fixedWidth
        var listWidth = calculateListViewWidth()
        return Math.max(0, (availableWidth - listWidth) / 2)
    }

    // 当内容或尺寸变化时更新布局
    Connections {
        target: lessonsBackend
        function onLessonsUpdated() {
            leftSpacer.width = Qt.binding(calculateSpacerWidth)
            rightSpacer.width = Qt.binding(calculateSpacerWidth)
            lessonsListView.width = Qt.binding(calculateListViewWidth)
        }
    }

    // 初始绑定
    Component.onCompleted: {
        leftSpacer.width = Qt.binding(calculateSpacerWidth)
        rightSpacer.width = Qt.binding(calculateSpacerWidth)
        lessonsListView.width = Qt.binding(calculateListViewWidth)
    }
}