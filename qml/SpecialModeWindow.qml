import QtQuick 2.15
import RinUI
import QtQuick.Window 2.15

// QtQuick.Window 必须在 RinUI 之后 import，否则根 Window 会被解析为 RinUI 的 Window（带系统控件）

// 特殊模式（白板/熄屏）专用全屏窗口：进入时隐藏创建，动画完成后由 Python 端
// show()+FullScreen 直接显示（无渐变动画）全屏置顶；不能写 visibility:FullScreen（会覆盖 visible:false 创建即显示）。
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

    // 课程显示（左上角）；宽度须用 root.width（parent 为 contentItem，窗口隐藏时宽度为 0 导致布局错乱）
    Loader {
        id: uiLoader
        objectName: "specialUiLoader"
        source: "LessonsDisplay.qml"
        x: 4
        y: 4
        width: root.width - 8
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

    // 插件深浅色 → RinUI 主题同步（whiteboard 浅 / blackboard 深 / normal 随系统主题）
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
        onSettingsRequested: settingsDialog.openDialog()
    }

    // 右键打开菜单；已打开时再点空白关闭（左键由 closePolicy 关闭）不再重开
    MouseArea {
        id: rightClickArea
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        propagateComposedEvents: true
        z: 999
        // 记录按下时菜单是否已打开，避免松开后在空白处重开
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

    // 设置对话框：模态遮罩在 Overlay 层天然最上层；打开时禁用 mask（否则被裁剪），关闭时恢复
    SettingsDialog {
        id: settingsDialog
    }
}
