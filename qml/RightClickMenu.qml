import QtQuick 2.15
import QtQuick.Window 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// 右键菜单（模仿主程序小组件，复用 RinUI Menu）：一般模式仅"设置"，特殊模式加"退出xx模式"。
// 定位：右键在胶囊内→胶囊下边框下方 5px，否则鼠标位置，随后避让屏幕边缘；
// 打开动画从上至下平移+展开+渐变；打开前移除 mask、关闭时恢复。
Menu {
    id: root

    // 设置项被点击：由宿主窗口决定打开设置对话框（各窗口自行连接）
    signal settingsRequested()

    position: Position.None  // 手动定位到鼠标位置，不跳到父项下方

    // 打开动画（手动定位时 position 为 None，RinUI 默认动画无位移，自行实现）
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

    // release 在菜单外或 Esc 关闭；不用 CloseOnPressOutside（打开瞬间鼠标在菜单外会一开就关）
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
        // RinUI 主题由窗口统一同步（见 FullScreenWindow.syncRinuiTheme）
        var targetX = x
        var targetY = y

        // 避让胶囊：右键在胶囊内则菜单放到其下边框下方 5px（正常模式=小组件本体，特殊模式=顶部课程条）
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
        // 打开前移除 mask 使动画全程可见，并强制所有插件窗口置顶
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
