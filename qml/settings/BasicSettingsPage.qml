import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "基本"设置页：小组件图层设置项（自动保存）。
// 根为 ColumnLayout（与主程序 SettingsLayout 一致），设置项从上到下依次排开，
// 由 SettingsDialog 的 Flickable 承载滚动。
// ComboBox 写法与主程序（Class-Widgets-2 General/Index.qml "Window Layer"）完全一致：
// 静态 ListModel + textRole + onCurrentIndexChanged(if focus) + Component.onCompleted 初始化。
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
            // 用 syncing 标记区分"程序化同步"与"用户变更"，不依赖 focus：
            // RinUI ComboBox 的下拉指示器是独立 ToolButton（focusPolicy:NoFocus），
            // 点击指示器打开菜单选择时 ComboBox 本体可能没有 focus，导致 if(focus)
            // 不写回、关闭设置重开后该项回退为默认值。
            property bool syncing: false
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
                syncing = true
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
