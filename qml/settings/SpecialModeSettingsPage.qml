import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "特殊模式"设置页：倒计时样式、下课后自动关闭设置项（自动保存）。
// 根为 ColumnLayout（与主程序 SettingsLayout 一致），设置项从上到下依次排开，
// 由 SettingsDialog 的 Flickable 承载滚动。
// ComboBox/SpinBox 写法与主程序完全一致（静态 ListModel + textRole；onCurrentIndexChanged/onValueChanged + if(focus)）。
ColumnLayout {
    id: root
    spacing: 4

    Text {
        typography: Typography.BodyStrong
        text: "熄屏/白板模式"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_timer_20_regular"
        title: "倒计时样式"
        description: "熄屏/白板模式下高亮课程右侧倒计时的显示字号"

        ComboBox {
            model: ListModel {
                ListElement { text: "默认字号"; value: "default" }
                ListElement { text: "大字号"; value: "large" }
            }
            textRole: "text"

            onCurrentIndexChanged: if (focus) settingsBackend.setString("countdown_style", model.get(currentIndex).value)

            Component.onCompleted: {
                for (var i = 0; i < model.count; i++) {
                    if (model.get(i).value === settingsBackend.getString("countdown_style")) {
                        currentIndex = i
                        break
                    }
                }
            }
        }
    }

    // 下课后自动关闭：header 右侧放开关，展开项内提供延迟时间（整数 + 单位）
    SettingExpander {
        Layout.fillWidth: true
        icon.name: "ic_fluent_power_20_regular"
        title: "下课后自动关闭"
        description: "在下课后的一定时间关闭熄屏/白板模式"

        // header 右侧开关
        content: SettingsSwitch {
            settingKey: "auto_close_after_class"
        }

        // 展开项：延迟时间（SpinBox 可输入 + 单位 ComboBox）
        SettingItem {
            title: "延迟时间"
            description: "下课后关闭熄屏/白板模式的延迟时间"

            RowLayout {
                spacing: 8

                SpinBox {
                    from: 0
                    to: 60
                    stepSize: 1
                    editable: true
                    // 与主程序一致：仅用户交互（focus）时写回
                    onValueChanged: if (focus) settingsBackend.setInt("auto_close_delay", value)
                    Component.onCompleted: value = settingsBackend.getInt("auto_close_delay")
                }

                ComboBox {
                    model: ListModel {
                        ListElement { text: "分"; value: "min" }
                        ListElement { text: "秒"; value: "sec" }
                    }
                    textRole: "text"

                    onCurrentIndexChanged: if (focus) settingsBackend.setString("auto_close_unit", model.get(currentIndex).value)

                    Component.onCompleted: {
                        for (var i = 0; i < model.count; i++) {
                            if (model.get(i).value === settingsBackend.getString("auto_close_unit")) {
                                currentIndex = i
                                break
                            }
                        }
                    }
                }
            }
        }
    }
}
