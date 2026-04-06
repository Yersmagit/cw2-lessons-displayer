import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import Qt5Compat.GraphicalEffects
import RinUI

Item {
    id: root
    height: 54

    // 根据模式计算实际暗色主题
    readonly property bool effectiveDarkTheme: {
        if (lessonsBackend.mode === "whiteboard") return false
        if (lessonsBackend.mode === "blackboard") return true
        return lessonsBackend.isDarkTheme
    }

    // 背景颜色：特殊模式纯色，正常模式半透明，根据配置调整不透明度
    readonly property color bgColor: {
        if (lessonsBackend.mode === "whiteboard") {
            return Qt.rgba(255/255, 255/255, 255/255, 1)
        } else if (lessonsBackend.mode === "blackboard") {
            return Qt.rgba(0/255, 0/255, 0/255, 1)
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

    readonly property real borderWidth: 1.5
    readonly property real radius: 27

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
        Item { width: 13; height: parent.height }

        // 换课按钮（禁用）
        RoundButton {
            id: switchButton
            enabled: false
            implicitWidth: 30
            implicitHeight: 30
            icon.name: "ic_fluent_arrow_swap_20_regular"
            anchors.verticalCenter: parent.verticalCenter
            highlighted: effectiveDarkTheme
            primaryColor: effectiveDarkTheme ? "#444" : undefined
        }

        Item { width: 16; height: parent.height }

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
            spacing: 5
            clip: true
            height: lessonsBackend.mode === "normal" ? 40 : 46
            anchors.verticalCenter: parent.verticalCenter
            width: calculateListViewWidth()
            contentWidth: childrenRect.width

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
                        property real foldedWidth: lessonAbbr.contentWidth + 10
                        property real expandedWidth: 30 + 8 + lessonFullName.contentWidth + 22 + remainingText.implicitWidth + 20
                        property real targetWidth: foldedWidth

                        width: targetWidth
                        height: lessonsBackend.mode === "normal" ? 40 : 46

                        Behavior on width {
                            NumberAnimation { duration: 400; easing.type: Easing.OutCubic }
                        }

                        function updateTargetWidth() {
                            var newWidth = expanded ? expandedWidth : foldedWidth
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
                            radius: lessonsBackend.mode === "normal" ? 20 : 23
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
                                    return 2
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

                        Text {
                            id: lessonAbbr
                            visible: !expanded
                            anchors.centerIn: parent
                            text: modelData.abbr
                            font.pixelSize: 28
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

                        Row {
                            visible: expanded
                            anchors.left: parent.left
                            anchors.leftMargin: 8
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 0

                            Icon {
                                id: iconItem
                                width: 30
                                height: parent.height
                                size: 30
                                icon: lessonsBackend.currentIcon
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                            }

                            Item { width: 8; height: 1 }

                            Text {
                                id: lessonFullName
                                text: modelData.fullName
                                font.pixelSize: 27
                                font.family: lessonsBackend.fontFamily
                                font.weight: lessonsBackend.fontWeight
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                                Behavior on color {
                                    ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
                                }
                            }

                            Item {
                                id: separatorContainer
                                width: 22
                                height: parent.height
                                Rectangle {
                                    width: 2
                                    height: 28
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
                                font.pixelSize: 16
                                font.family: lessonsBackend.fontFamily
                                font.weight: lessonsBackend.fontWeight
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                                verticalAlignment: Text.AlignVCenter
                                height: parent.height
                                Behavior on color {
                                    ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
                                }
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
                        width: 10
                        height: lessonsBackend.mode === "normal" ? 40 : 46

                        Rectangle {
                            width: 2
                            height: 32
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
                        property real iconWidth: 24
                        width: iconWidth + 8 + textWidth + 20
                        height: lessonsBackend.mode === "normal" ? 40 : 46

                        Row {
                            anchors.centerIn: parent
                            spacing: 8

                            Icon {
                                width: 24
                                height: parent.height
                                size: 24
                                icon: modelData.icon
                                color: effectiveDarkTheme ? "#ffffff" : "#000000"
                            }

                            Text {
                                id: placeholderText
                                text: modelData.text
                                font.pixelSize: 16
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

            Connections {
                target: lessonsBackend
                function onScrollRequested(index) {
                    if (lessonsListView.autoScrollEnabled && lessonsListView.contentWidth > lessonsListView.width) {
                        lessonsListView.scrollToIndex(index)
                    }
                }
            }

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

            NumberAnimation {
                id: scrollAnimation
                target: lessonsListView
                property: "contentX"
                duration: 400
                easing.type: Easing.OutCubic
            }

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

        Item { width: 16; height: parent.height }

        // 按钮1：白板模式/切换
        RoundButton {
            id: button1
            implicitWidth: 30
            implicitHeight: 30
            icon.name: {
                if (lessonsBackend.mode === "whiteboard") return "ic_fluent_weather_moon_20_regular"
                if (lessonsBackend.mode === "blackboard") return "ic_fluent_weather_sunny_20_regular"
                return "ic_fluent_weather_sunny_20_regular"
            }
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

        Item { width: 12; height: parent.height }

        // 按钮2：熄屏模式/退出
        RoundButton {
            id: button2
            implicitWidth: 30
            implicitHeight: 30
            icon.name: {
                if (lessonsBackend.mode !== "normal") return "ic_fluent_arrow_exit_20_regular"
                return "ic_fluent_weather_moon_20_regular"
            }
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

        Item { width: 13; height: parent.height }
    }

    // 计算列表视图宽度
    function calculateListViewWidth() {
        var fixedWidth = 13 + 30 + 16 + 16 + 30 + 12 + 30 + 13
        var availableWidth = root.width - fixedWidth
        var contentWidth = lessonsListView.contentWidth
        return Math.min(contentWidth, availableWidth)
    }

    // 计算空白宽度
    function calculateSpacerWidth() {
        var fixedWidth = 13 + 30 + 16 + 16 + 30 + 12 + 30 + 13
        var availableWidth = root.width - fixedWidth
        var listWidth = calculateListViewWidth()
        return Math.max(0, (availableWidth - listWidth) / 2)
    }

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

    Component.onCompleted: {
        leftSpacer.width = Qt.binding(calculateSpacerWidth)
        rightSpacer.width = Qt.binding(calculateSpacerWidth)
        lessonsListView.width = Qt.binding(calculateListViewWidth)
    }
}