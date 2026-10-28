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

    // 交互智能平板才有“手写板模式”右侧胶囊按钮；投影设备右侧是白板/熄屏双按钮（随设备类型自动刷新）
    readonly property bool isPanel: settingsBackend.deviceType === "interactive_panel"

    Text {
        typography: Typography.BodyStrong
        text: "基本"
    }

    // 设备类型：默认展开，两个单选项并排且互斥；自动保存
    SettingExpander {
        Layout.fillWidth: true
        icon.name: "ic_fluent_tablet_20_regular"
        title: "设备类型"
        description: "选择“交互智能平板”后将提供笔书写功能"
        expanded: true

        SettingItem {
            // syncing 区分"程序化同步"与"用户变更"；初始为 true，避免初始化期 checked 赋值误写回
            // RadioButton 经 action 默认属性进内部 rightContent，须用 id 显式引用 syncing
            id: deviceItem
            property bool syncing: true

            ButtonGroup { id: deviceGroup }

            RadioButton {
                id: interactiveRadio
                text: "交互智能平板"
                ButtonGroup.group: deviceGroup
                onCheckedChanged: {
                    if (!deviceItem.syncing && checked)
                        settingsBackend.setString("device_type", "interactive_panel")
                }
            }
            RadioButton {
                id: projectorRadio
                text: "投影设备或其他"
                ButtonGroup.group: deviceGroup
                onCheckedChanged: {
                    if (!deviceItem.syncing && checked)
                        settingsBackend.setString("device_type", "projector")
                }
            }

            Component.onCompleted: {
                if (settingsBackend.getString("device_type") === "interactive_panel")
                    interactiveRadio.checked = true
                else
                    projectorRadio.checked = true
                deviceItem.syncing = false
            }
        }
    }

    // 第二分组标题（仿高级页）：与上方保持 8px 间距（ColumnLayout spacing 4 + 额外 4px）
    Text {
        typography: Typography.BodyStrong
        text: "小组件"
        Layout.topMargin: 4
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_layer_20_regular"
        title: "小组件层级"
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

    // 手写板模式（平板设备顶部“手写板模式”胶囊按钮）：单击后打开的模式，默认黑板模式。
    // 仅交互智能平板有该右侧胶囊；投影设备右侧是白板/熄屏双按钮 → 非平板禁用。
    // SettingCard 本身无禁用样式（Frame），需 enabled 禁交互 + 整卡 opacity 弱化（同 Expander 0.65 淡法）
    SettingCard {
        Layout.fillWidth: true
        enabled: root.isPanel
        opacity: root.isPanel ? 1.0 : 0.6
        Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutQuad } }
        objectName: "specialModeCard"
        icon.name: "ic_fluent_whiteboard_20_regular"
        title: "手写板模式"
        description: "单击课程列表右侧按钮后打开的模式"

        ComboBox {
            property bool syncing: true
            model: ListModel {
                ListElement { text: "黑板模式"; value: "blackboard" }
                ListElement { text: "白板模式"; value: "whiteboard" }
            }
            textRole: "text"

            onCurrentIndexChanged: {
                if (!syncing)
                    settingsBackend.setString("special_mode_action", model.get(currentIndex).value)
            }

            Component.onCompleted: {
                for (var i = 0; i < model.count; i++) {
                    if (model.get(i).value === settingsBackend.getString("special_mode_action")) {
                        currentIndex = i
                        break
                    }
                }
                syncing = false
            }
        }
    }

    // 迷你模式时隐藏：小组件进入迷你模式时自动隐藏灵动条小组件（默认关闭，仅一般模式生效）
    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_eye_off_20_regular"
        title: "迷你模式时隐藏"
        description: "在小组件进入迷你模式时不显示灵动条小组件"

        SettingsSwitch {
            settingKey: "hide_in_mini_mode"
        }
    }
}
