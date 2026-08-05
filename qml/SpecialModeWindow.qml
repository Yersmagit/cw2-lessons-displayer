import QtQuick 2.15
import QtQuick.Window 2.15

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
}
