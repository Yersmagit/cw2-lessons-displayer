import QtQuick 2.15
import RinUI
import QtQuick.Window 2.15

// 注意：QtQuick.Window 必须在 RinUI 之后 import，否则根 Window 会被解析为
// RinUI 的 Window（带标题栏/最小化最大化关闭按钮/纯色背景）。

// 特殊模式（白板/熄屏）专用全屏窗口。
// 每次进入特殊模式时以隐藏状态创建（visible:false），利用旧窗口启动动画时间完成
// 加载，待旧窗口动画播放完成后由 Python 端 show()+setWindowState(FullScreen) 直接
// 显示（无渐变动画），以全新窗口状态全屏置顶，避免复用胶囊窗口时任务栏浮在其上。
// 注意：不能在此写 visibility:Window.FullScreen —— 常量绑定会在加载时覆盖 visible:false，
// 导致窗口创建即显示。
Window {
    id: root
    visible: false
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
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

    // 课程显示（复用胶囊 UI 内容，位于左上角）
    Loader {
        id: uiLoader
        objectName: "specialUiLoader"
        source: "LessonsDisplay.qml"
        x: 4
        y: 4
        width: parent.width - 8
        height: 54 * lessonsBackend.scaleFactor
        onStatusChanged: {
            if (status === Loader.Ready || status === Loader.Error) {
                root.specialReady()
            }
        }
    }

    signal specialReady()

    // 首次启动前先同步一次 RinUI 主题
    Component.onCompleted: {
        root.syncRinuiTheme()
    }

    // 插件深浅色 → RinUI 主题同步：whiteboard 浅 / blackboard 深 / normal 随系统主题。
    // RinUI 控件（RoundButton/滚动条/右键菜单等）样式由 RinUI 决定。
    function syncRinuiTheme() {
        var dark = lessonsBackend.mode === "whiteboard" ? false
            : lessonsBackend.mode === "blackboard" ? true
            : lessonsBackend.isDarkTheme
        Theme.currentTheme = dark ? Theme.dark : Theme.light
    }

    // 模式/系统主题变化时同步（与 LessonsDisplay 自定义 UI 的 effectiveDarkTheme 同帧更新）
    Connections {
        target: lessonsBackend
        function onModeChanged() { root.syncRinuiTheme() }
        function onThemeChanged() { root.syncRinuiTheme() }
    }

    // 右键菜单（模仿主程序小组件右键菜单）：特殊模式提供"设置"与"退出xx模式"
    RightClickMenu {
        id: widgetMenu
    }

    // 右键触发 + 菜单已打开时关闭。
    // 菜单未打开：右键在空白处打开；菜单已打开：点击空白（右键关闭，左键由
    // closePolicy 关闭）不再重新打开。
    MouseArea {
        id: rightClickArea
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        propagateComposedEvents: true
        z: 999
        // 记录右键按下时菜单是否已打开：若已打开，松开后（closePolicy 已关闭菜单）
        // 不应在空白处再次打开
        property bool pressWhileOpen: false
        onPressed: {
            if (widgetMenu.opened) {
                pressWhileOpen = true
            }
        }
        onClicked: (mouse) => {
            if (widgetMenu.opened) {
                widgetMenu.close()
            } else if (!pressWhileOpen) {
                widgetMenu.openAt(mouse.x, mouse.y)
            }
            pressWhileOpen = false
        }
    }
}
