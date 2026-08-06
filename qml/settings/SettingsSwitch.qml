import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// 设置项 Switch：自动从 settingsBackend 加载初始值，用户变更时自动保存（setBool），
// 并监听 settingsChanged，使"恢复默认设置"等外部变更能同步刷新界面。
Switch {
    id: root

    property string settingKey: ""

    // 程序化同步期间置 true，避免 onToggled 把同步值误写回配置
    property bool syncing: false

    Layout.alignment: Qt.AlignVCenter

    Component.onCompleted: root.syncFromBackend()

    onToggled: {
        if (!root.syncing)
            settingsBackend.setBool(root.settingKey, root.checked)
    }

    function syncFromBackend() {
        root.syncing = true
        root.checked = settingsBackend.getBool(root.settingKey)
        root.syncing = false
    }

    Connections {
        target: settingsBackend
        function onSettingsChanged() {
            root.syncFromBackend()
        }
    }
}
