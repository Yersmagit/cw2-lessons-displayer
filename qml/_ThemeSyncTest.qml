import QtQuick 2.15
import QtQuick.Window 2.15
import RinUI

// 临时验证：syncRinuiTheme 驱动 RinUI 主题，测试后删除
Window {
    id: root
    visible: true
    width: 300
    height: 200

    function syncRinuiTheme() {
        var dark = lessonsBackend.mode === "whiteboard" ? false
            : lessonsBackend.mode === "blackboard" ? true
            : lessonsBackend.isDarkTheme
        Theme.currentTheme = dark ? Theme.dark : Theme.light
        console.log("SYNC mode=", lessonsBackend.mode, "isDark=", lessonsBackend.isDarkTheme,
                    "-> themeDark=", Theme.currentTheme.isDark)
    }

    Connections {
        target: lessonsBackend
        function onModeChanged() { root.syncRinuiTheme() }
        function onThemeChanged() { root.syncRinuiTheme() }
    }

    Component.onCompleted: {
        root.syncRinuiTheme()                       // 初始：normal+浅
        lessonsBackend.setMode("whiteboard")        // 白板→浅
        lessonsBackend.setMode("blackboard")        // 熄屏→深
        lessonsBackend.setMode("normal")            // normal→浅
        lessonsBackend.setDark(true)                // 系统深色→深
        lessonsBackend.setMode("whiteboard")        // 白板→浅
        lessonsBackend.setMode("blackboard")        // 熄屏→深
    }
}
