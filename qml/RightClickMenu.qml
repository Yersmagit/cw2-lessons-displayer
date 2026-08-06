import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// 右键菜单（模仿主程序小组件右键菜单，复用 RinUI 的 Menu/MenuItem/MenuSeparator）。
// 一般模式：仅"设置"；特殊模式（白板/熄屏）：额外提供"退出xx模式"。
// 定位规则（在菜单显示前完成）：右键点在胶囊形 UI 内 → 菜单放到胶囊下边框下方 5px；
// 否则在鼠标位置；随后避让屏幕边缘（优先级更高）。
// 打开动画与主程序小组件菜单一致：从上至下平移 + 展开 + 渐变。
// 菜单打开前通知后端移除窗口 mask（使菜单可显示在胶囊外且动画全程可见），关闭时恢复 mask。
// 左键/右键点击菜单以外区域或按 Esc 均关闭菜单（右键由窗口 MouseArea 关闭并避免重开）。
Menu {
    id: root

    // 设置项被点击：由宿主窗口决定打开设置对话框（各窗口自行连接）
    signal settingsRequested()

    position: Position.None  // 手动定位到鼠标位置，不跳到父项下方

    // 打开动画：与主程序小组件右键菜单一致（从上至下边平移边渐变）。
    // 手动定位时 position 为 None，RinUI 默认动画 from==to 无位移，这里自行实现。
    enter: Transition {
        ParallelAnimation {
            NumberAnimation {
                property: "opacity"
                from: 0
                to: 1
                duration: Utils.animationSpeed
                easing.type: Easing.InOutQuart
            }
            NumberAnimation {
                property: "height"
                from: 0
                to: root.implicitHeight
                duration: Utils.animationSpeed
                easing.type: Easing.OutQuart
            }
            NumberAnimation {
                property: "y"
                from: root.y - root.implicitHeight / 2
                to: root.y
                duration: Utils.animationSpeedMiddle
                easing.type: Easing.OutQuint
            }
        }
    }

    // 点击菜单以外区域（release 在菜单外）或按 Esc 时关闭（处理左键点击空白关闭）。
    // 不用 CloseOnPressOutside：菜单常显示在鼠标/胶囊附近，打开瞬间鼠标在菜单外，
    // 该策略会让菜单一打开就被关闭。
    closePolicy: Popup.CloseOnReleaseOutside | Popup.CloseOnEscape

    // 是否处于特殊模式（决定是否显示"退出xx模式"项）
    readonly property bool inSpecialMode: lessonsBackend.mode !== "normal"

    MenuItem {
        text: qsTr("设置")
        icon.name: "ic_fluent_settings_20_regular"
        onTriggered: {
            // 先关闭菜单（避免 Popup 浮在设置对话框上方），再通知宿主打开设置
            root.close()
            root.settingsRequested()
        }
    }

    MenuSeparator {
        visible: root.inSpecialMode
    }

    MenuItem {
        visible: root.inSpecialMode
        text: {
            if (lessonsBackend.mode === "whiteboard") return qsTr("退出白板模式")
            if (lessonsBackend.mode === "blackboard") return qsTr("退出熄屏模式")
            return qsTr("退出特殊模式")
        }
        icon.name: "ic_fluent_arrow_exit_20_regular"
        onTriggered: {
            // 退出信号正常传递到后端
            lessonsBackend.exitSpecialMode()
        }
    }

    // 在指定位置（窗口内坐标）弹出；显示前完成定位与屏幕边缘避让。
    function openAt(x, y) {
        // RinUI 主题由窗口统一同步（见 FullScreenWindow/SpecialModeWindow.syncRinuiTheme）
        var targetX = x
        var targetY = y

        // 避让胶囊形 UI：右键点在胶囊区域内时，菜单放到胶囊下边框下方 5px（横坐标不变）。
        // 正常模式胶囊=小组件本体（uiX/uiY/uiWidth）；特殊模式胶囊=顶部课程条
        // （左上角 4,4，宽度=屏幕宽-8）。
        var capX, capY, capW
        if (lessonsBackend.mode === "normal") {
            capX = lessonsBackend.uiX
            capY = lessonsBackend.uiY
            capW = lessonsBackend.uiWidth
        } else {
            capX = 4
            capY = 4
            capW = Screen.width - 8
        }
        var capH = 54 * lessonsBackend.scaleFactor
        if (x >= capX && x <= capX + capW && y >= capY && y <= capY + capH) {
            targetY = capY + capH + 5
        }

        // 预估菜单尺寸（用当前/隐式尺寸，保证避让在显示前完成）
        var mw = root.width > 0 ? root.width : (root.implicitWidth > 0 ? root.implicitWidth : 80)
        var mh = root.height > 0 ? root.height : (root.implicitHeight > 0 ? root.implicitHeight : 44)

        // 避让屏幕边缘（优先级更高）
        var sW = Screen.width
        var sH = Screen.height
        if (targetX < 0) targetX = 0
        if (targetX + mw > sW) targetX = Math.max(0, sW - mw)
        if (targetY < 0) targetY = 0
        if (targetY + mh > sH) targetY = Math.max(0, sH - mh)

        root.x = targetX
        root.y = targetY
        // 打开前移除 mask：使打开动画（平移+渐变）在无 mask 的窗口上全程可见；
        // 同时强制所有插件窗口置顶（宿主窗口 winId 早已存在，open 前置顶即可生效）
        lessonsBackend.hideWidgetMask()
        lessonsBackend.holdTopmost()
        root.open()
    }

    // 菜单关闭：通知后端恢复窗口 mask，恢复正常胶囊显示；释放置顶
    onClosed: {
        lessonsBackend.showWidgetMask()
        lessonsBackend.releaseTopmost()
    }
}
