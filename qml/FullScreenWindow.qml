import QtQuick 2.15
import RinUI
import QtQuick.Window 2.15

// QtQuick.Window 必须在 RinUI 之后 import，否则根 Window 会被解析为 RinUI 的 Window（带系统控件与纯色底）
Window {
    id: root
    visible: false

    // ===== 小组件迷你模式适配 =====
    // 小组件进入迷你模式（主程序 preferences.mini_mode）时，一般模式（mode==="normal"）下课程条启用迷你模式：
    //  - 缩放系数额外 ×0.7（视觉整体缩小，带 300ms 缩放渐变动画；锚点随小组件停靠边自动贴合）；
    //  - "迷你模式时隐藏"开启时整条透明度渐隐（复用 opacity Behavior，400ms 渐变动画）。
    // 特殊模式（whiteboard/blackboard）一律不缩放、不隐藏（缩放/透明度因子保持 1）。
    readonly property bool normalMiniMode: lessonsBackend.mode === "normal" && lessonsBackend.miniMode
    readonly property real miniHideFactor: (root.normalMiniMode && settingsBackend.hideInMiniMode) ? 0.0 : 1.0
    readonly property real miniScaleFactor: root.normalMiniMode ? 0.7 : 1.0

    // flags 绑定模式、浮层与图层：特殊模式/浮层置顶；正常模式跟随图层策略（互斥），置顶稳定后无需每秒刷新
    flags: {
        var baseFlags = Qt.FramelessWindowHint | Qt.Tool;
        // 特殊模式或浮层弹出：置顶
        if (lessonsBackend.mode !== "normal" || lessonsBackend.popupOpen) {
            return baseFlags | Qt.WindowStaysOnTopHint;
        }
        // 正常模式：跟随小组件图层策略（置顶/置底/普通互斥）
        if (lessonsBackend.layerTopmost) {
            return baseFlags | Qt.WindowStaysOnTopHint;
        }
        if (lessonsBackend.layerBottommost) {
            return baseFlags | Qt.WindowStaysOnBottomHint;
        }
        return baseFlags;
    }
    color: "transparent"

    // visibility 须尊重 visible（避免 visible/visibility 冲突启动即显示）：visible:false 时保持 Hidden，由 Python 控制显示
    visibility: {
        if (!visible)
            return Window.Hidden
        return lessonsBackend.mode !== "normal" ? Window.FullScreen : Window.Windowed
    }

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
        // 特殊模式宽度须用 root.width（parent 为 contentItem，隐藏时宽度可能为 0 导致布局错乱）
        x: lessonsBackend.mode === "normal" ? lessonsBackend.uiX : 4
        y: lessonsBackend.mode === "normal" ? lessonsBackend.uiY : 4
        // 迷你模式（一般模式）：源宽放大 1/0.7 —— 配合 scale 0.7 水平方向抵消，
        // 使视觉条宽恒 = 小组件总宽（uiWidth，随小组件迷你自动变窄），并经下方 width Behavior 平滑过渡。
        width: lessonsBackend.mode === "normal"
            ? (root.normalMiniMode ? Math.round(lessonsBackend.uiWidth / 0.7) : lessonsBackend.uiWidth)
            : root.width - 8
        height: 54 * lessonsBackend.scaleFactor
        // 透明度 = 主程序隐藏(uiOpacity) × 迷你模式自动隐藏因子（渐隐/渐显走下方 opacity Behavior）
        opacity: lessonsBackend.uiOpacity * root.miniHideFactor
        // 小组件迷你模式（一般模式）：视觉额外缩放 ×0.7（带缩放渐变动画）；特殊模式恒 1
        scale: root.miniScaleFactor
        // 缩放锚点：X 恒取左缘（源宽已放大抵消 → 视觉左缘=loader.x、视觉宽=小组件总宽）；
        // Y 依小组件垂直停靠固定相应边，使视觉胶囊贴合小组件。未缩放时原点无关紧要。
        transformOrigin: {
            if (!lessonsBackend.miniMode || lessonsBackend.mode !== "normal")
                return Item.Center
            var a = lessonsBackend.anchorPoint
            if (a.indexOf("bottom") >= 0) return Item.BottomLeft
            if (a.indexOf("top") >= 0) return Item.TopLeft
            return Item.Left
        }
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
        Behavior on scale { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
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

    // 纯平移动画结束时通知后端恢复 mask（后端用引用计数保证只恢复一次）
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

    // 插件深浅色 → RinUI 主题同步（whiteboard 浅、blackboard 深、normal 随系统主题）
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

    // 特殊模式启动动画（400ms）完成后发信号，通知专用全屏窗口直接显示
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