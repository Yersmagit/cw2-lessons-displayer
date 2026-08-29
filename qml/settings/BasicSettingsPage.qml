import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "基本"设置页：小组件图层设置项（自动保存）。根为 ColumnLayout，由 SettingsDialog 的 Flickable 承载滚动。
// ComboBox 写法与主程序一致（静态 ListModel + textRole + onCurrentIndexChanged(if focus)）。
// ⚠️ 不要改成动态 append model（RinUI ComboBox 弹出菜单首次打开会有大片空白）。
ColumnLayout {
    id: root
    spacing: 4

    Text {
        typography: Typography.BodyStrong
        text: "基本"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_layer_20_regular"
        title: "小组件图层"
        description: "控制本插件小组件的窗口层级"

        ComboBox {
            // syncing 区分"程序化同步"与"用户变更"；⚠️ 必须初始为 true，否则模型填充时会把 index 0 误写回（覆盖已保存设置）
            property bool syncing: true
            model: ListModel {
                ListElement { text: "跟随软件设置"; value: "follow" }
                ListElement { text: "始终置顶"; value: "top" }
                ListElement { text: "始终置底"; value: "bottom" }
            }
            textRole: "text"

            onCurrentIndexChanged: {
                if (!syncing)
                    settingsBackend.setString("widgets_layer", model.get(currentIndex).value)
            }

            Component.onCompleted: {
                for (var i = 0; i < model.count; i++) {
                    if (model.get(i).value === settingsBackend.getString("widgets_layer")) {
                        currentIndex = i
                        break
                    }
                }
                syncing = false
            }
        }
    }
}
