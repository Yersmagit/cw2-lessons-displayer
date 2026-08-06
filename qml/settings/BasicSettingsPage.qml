import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "基本"设置页：占位 Switch 设置项（自动保存，暂无实际作用）。
// 根为 ColumnLayout（与主程序 SettingsLayout 一致），设置项从上到下依次排开，
// 由 SettingsDialog 的 Flickable 承载滚动。
ColumnLayout {
    id: root
    spacing: 4

    Text {
        typography: Typography.BodyStrong
        text: "基本"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_settings_20_regular"
        title: "占位开关"
        description: "该设置项暂无实际作用，用于演示设置自动保存"

        SettingsSwitch {
            settingKey: "basic_placeholder"
        }
    }
}
