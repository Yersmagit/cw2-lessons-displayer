import QtQuick 2.15
import RinUI
import QtQuick.Window 2.15

// 注意：QtQuick.Window 必须在 RinUI 之后 import，否则根 Window 会被解析为
// RinUI 的 Window（带标题栏/最小化最大化关闭按钮/纯色背景），导致插件窗口
// 出现系统窗口控件与纯色底。
Window {
    id: root
    visible: false
    // flags 绑定到模式与浮层：特殊模式或右键菜单/设置页弹出时置顶。
    // （模仿特殊模式：QML 层 flags 直接带 WindowStaysOnTopHint，窗口创建/显示即置顶，
    // 比 Python 运行时 setFlag 更可靠。）
    // ⚠️ 小组件图层（置顶/置底）不在此绑定——由 Python `_apply_layer_flags()` 统一互斥
    // 控制（WindowStaysOnTopHint/WindowStaysOnBottomHint + SetWindowPos），避免 QML 绑定
    // 重新求值时覆盖/残留 top/bottom hint 导致置顶置底切换不可靠。
    flags: {
        var baseFlags = Qt.FramelessWindowHint | Qt.Tool;
        if (lessonsBackend.mode !== "normal" || lessonsBackend.popupOpen) {
            return baseFlags | Qt.WindowStaysOnTopHint;
        } else {
            return baseFlags;
        }
    }
    color: "transparent"

    // 窗口可见性：特殊模式时全屏，正常模式时普通窗口
    visibility: lessonsBackend.mode !== "normal" ? Window.FullScreen : Window.Windowed

    // 窗口始终全屏且不透明（全屏模式下尺寸自动为屏幕大小，但保留绑定以防万一）
    x: 0
    y: 0
    width: Screen.width
    height: Screen.height

    // 背景层（仅在特殊模式下显示，带淡入淡出动画和颜色动画）
    Rectangle {
        id: backgroundLayer
        anchors.fill: parent
        color: lessonsBackend.mode === "whiteboard" ? "white" : (lessonsBackend.mode === "blackboard" ? "black" : "transparent")
        opacity: lessonsBackend.mode === "normal" ? 0 : 1
        z: 0

        Behavior on color {
            ColorAnimation { duration: 400; easing.type: Easing.OutCubic }
        }
        Behavior on opacity {
            NumberAnimation { duration: 400; easing.type: Easing.OutCubic }
        }
    }

    Loader {
        id: uiLoader
        objectName: "uiLoader"
        source: "LessonsDisplay.qml"
        asynchronous: false
        // 根据模式动态绑定位置和宽度
        // 注意：特殊模式宽度用 root.width（Window 本身）而非 parent.width——parent 是
        // Window 的 contentItem（QQuickRootItem），窗口隐藏时其宽度为 0，会导致
        // LessonsDisplay 布局错乱（见 SpecialModeWindow 注释）。
        x: lessonsBackend.mode === "normal" ? lessonsBackend.uiX : 4
        y: lessonsBackend.mode === "normal" ? lessonsBackend.uiY : 4
        width: lessonsBackend.mode === "normal" ? lessonsBackend.uiWidth : root.width - 8
        height: 54 * lessonsBackend.scaleFactor
        opacity: lessonsBackend.uiOpacity  // 透明度绑定后端属性，实现淡入淡出
        z: 1

        Behavior on x {
            id: xBehavior
            NumberAnimation {
                id: xAnim
                duration: 400
                easing.type: Easing.OutQuint
                onStopped: root.onTranslateAnimStopped()
            }
        }
        Behavior on y {
            id: yBehavior
            NumberAnimation {
                id: yAnim
                duration: 400
                easing.type: Easing.OutQuint
                onStopped: root.onTranslateAnimStopped()
            }
        }
        Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }
        Behavior on height { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }
        Behavior on opacity { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }

        onStatusChanged: {
            console.log("Loader status changed:", status)
            if (status === Loader.Ready) {
                console.log("Loader ready, item:", item)
                root.uiReady()
            } else if (status === Loader.Error) {
                console.log("Loader error:", errorString())
                root.uiReady()
            }
        }
    }

    // 动画性能优化：纯平移动画（x/y）结束时通知后端恢复 mask。
    // x/y 动画可能同时/先后停止，后端用引用计数保证只恢复一次。
    // 宽度变化触发的 x/y 动画也会走到这里，但后端 _anim_optimize_active 为
    // False 时 endTranslateAnim 直接返回，不会误恢复 mask。
    function onTranslateAnimStopped() {
        lessonsBackend.endTranslateAnim()
    }

    function checkLoader() {
        if (uiLoader.status === Loader.Ready) {
            root.uiReady()
        } else if (uiLoader.status === Loader.Error) {
            console.log("Loader error:", uiLoader.errorString())
            root.uiReady()
        } else {
            Qt.callLater(checkLoader)
        }
    }

    Component.onCompleted: {
        console.log("FullScreenWindow completed")
        root.syncRinuiTheme()  // 首次启动前先同步一次 RinUI 主题
        Qt.callLater(checkLoader)
    }

    // 插件深浅色 → RinUI 主题同步：RinUI 控件（RoundButton/滚动条/右键菜单等）
    // 样式由 RinUI 决定；深浅色由一般/特殊模式 + 系统主题共同决定
    // （whiteboard 浅、blackboard 深、normal 随系统主题）。
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

    // 特殊模式启动动画（背景淡入、胶囊展开等，时长 400ms）播放完成后发出信号，
    // 通知已隐藏准备好的专用全屏窗口直接显示（无渐变动画），然后隐藏本窗口。
    Timer {
        id: specialAnimTimer
        interval: 400
        running: lessonsBackend.mode !== "normal"
        repeat: false
        onTriggered: root.specialAnimationFinished()
    }

    signal uiReady()
    signal specialAnimationFinished()

    // 右键菜单（模仿主程序小组件右键菜单）：一般模式仅"设置"，
    // 特殊模式额外提供"退出xx模式"；在鼠标位置弹出并钳制到可见区域。
    RightClickMenu {
        id: widgetMenu
        onSettingsRequested: settingsDialog.openDialog()
    }

    // 右键触发 + 菜单已打开时关闭。
    // 菜单未打开：右键在空白/胶囊处打开；菜单已打开：点击空白（右键关闭，左键由
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

    // 设置对话框（复用 RinUI Dialog，模态遮罩在 Overlay 层，天然位于最上层）：
    // 打开时禁用 mask（否则遮罩/对话框被窗口 mask 裁剪），关闭时恢复。
    SettingsDialog {
        id: settingsDialog
    }
}