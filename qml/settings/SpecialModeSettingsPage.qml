import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "特殊模式"设置页：倒计时样式、下课后自动关闭（自动保存）。根为 ColumnLayout，由 SettingsDialog 的 Flickable 承载滚动。
// ComboBox/SpinBox 写法与主程序完全一致（静态 ListModel；onCurrentIndexChanged/onValueChanged + if(focus)）。
ColumnLayout {
    id: root
    spacing: 4

    // 交互智能平板语境叫"手写板模式"，投影设备保持"熄屏/白板模式"（随设备类型设置自动刷新）
    readonly property bool isPanel: settingsBackend.deviceType === "interactive_panel"

    Text {
        typography: Typography.BodyStrong
        text: root.isPanel ? "手写板模式" : "熄屏/白板模式"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_timer_20_regular"
        title: "倒计时样式"
        description: root.isPanel
            ? "手写板模式下高亮课程右侧倒计时的显示字号"
            : "熄屏/白板模式下高亮课程右侧倒计时的显示字号"

        ComboBox {
            // syncing 区分"程序化同步"与"用户变更"；⚠️ 必须初始为 true，否则模型填充时会把 index 0 误写回（覆盖已保存设置）
            property bool syncing: true
            model: ListModel {
                ListElement { text: "默认字号"; value: "default" }
                ListElement { text: "大字号"; value: "large" }
            }
            textRole: "text"

            onCurrentIndexChanged: {
                if (!syncing)
                    settingsBackend.setString("countdown_style", model.get(currentIndex).value)
            }

            Component.onCompleted: {
                for (var i = 0; i < model.count; i++) {
                    if (model.get(i).value === settingsBackend.getString("countdown_style")) {
                        currentIndex = i
                        break
                    }
                }
                syncing = false
            }
        }
    }

    // 笔触仿真：使笔触随书写速度、压力变化而具有洇墨效果（速度→粗细）。
    // header 右侧开关控制是否启用；展开项内选择"洇墨程度"（响应灵敏度）。
    // 仅交互智能平板有笔书写；投影设备无笔 → 非平板禁用（Qt/RinUI enabled 传播灰显）
    SettingExpander {
        Layout.fillWidth: true
        enabled: root.isPanel
        objectName: "penSimulationGroup"
        icon.name: "ic_fluent_ink_stroke_20_regular"
        title: "笔触仿真"
        description: "使笔触随书写速度、压力变化而具有洇墨效果"

        content: SettingsSwitch {
            settingKey: "pen_speed_pressure"
        }

        SettingItem {
            title: "洇墨程度"
            description: "笔触洇墨/粗细随书写速度变化的响应程度"

            ComboBox {
                property bool syncing: true
                model: ListModel {
                    ListElement { text: "柔和"; value: "soft" }
                    ListElement { text: "标准"; value: "standard" }
                    ListElement { text: "灵敏"; value: "sensitive" }
                }
                textRole: "text"

                onCurrentIndexChanged: {
                    if (!syncing)
                        settingsBackend.setString("pen_speed_sensitivity", model.get(currentIndex).value)
                }

                Component.onCompleted: {
                    for (var i = 0; i < model.count; i++) {
                        if (model.get(i).value === settingsBackend.getString("pen_speed_sensitivity")) {
                            currentIndex = i
                            break
                        }
                    }
                    syncing = false
                }
            }
        }
    }

    // 下课后自动关闭：header 右侧放开关，展开项内提供延迟时间（整数 + 单位）
    SettingExpander {
        Layout.fillWidth: true
        icon.name: "ic_fluent_power_20_regular"
        title: "下课后自动关闭"
        description: root.isPanel
            ? "在下课后的一定时间关闭手写板模式"
            : "在下课后的一定时间关闭熄屏/白板模式"

        // header 右侧开关
        content: SettingsSwitch {
            settingKey: "auto_close_after_class"
        }

        // 展开项：延迟时间（SpinBox 可输入 + 单位 ComboBox）
        SettingItem {
            title: "延迟时间"
            description: root.isPanel
                ? "下课后关闭手写板模式的延迟时间"
                : "下课后关闭熄屏/白板模式的延迟时间"

            RowLayout {
                spacing: 8

                SpinBox {
                    // 同 ComboBox：syncing 初始为 true，避免初始化期 value 赋值被误写回
                    property bool syncing: true
                    from: 0
                    to: 1000
                    stepSize: 1
                    editable: true

                    // 值变化即保存（箭头/滚轮/editable 输入提交后）
                    onValueChanged: {
                        if (!syncing)
                            settingsBackend.setInt("auto_close_delay", value)
                    }

                    Component.onCompleted: {
                        value = settingsBackend.getInt("auto_close_delay")
                        syncing = false
                    }
                }

                ComboBox {
                    // 同倒计时样式 ComboBox：syncing 初始为 true，防止初始化误写回
                    property bool syncing: true
                    model: ListModel {
                        ListElement { text: "分"; value: "min" }
                        ListElement { text: "秒"; value: "sec" }
                    }
                    textRole: "text"

                    onCurrentIndexChanged: {
                        if (!syncing)
                            settingsBackend.setString("auto_close_unit", model.get(currentIndex).value)
                    }

                    Component.onCompleted: {
                        for (var i = 0; i < model.count; i++) {
                            if (model.get(i).value === settingsBackend.getString("auto_close_unit")) {
                                currentIndex = i
                                break
                            }
                        }
                        syncing = false
                    }
                }
            }
        }
    }
}
