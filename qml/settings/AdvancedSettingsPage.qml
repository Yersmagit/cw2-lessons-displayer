import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "高级"设置页：提供"恢复默认设置"按钮（清空配置文件，全部回落到源码默认值）。
// 根为 ColumnLayout（与主程序 SettingsLayout 一致），设置项从上到下依次排开，
// 由 SettingsDialog 的 Flickable 承载滚动。
ColumnLayout {
    id: root
    spacing: 4

    Text {
        typography: Typography.BodyStrong
        text: "高级"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_play_20_regular"
        title: "动画性能优化"
        description: "位置平移等动画播放期间暂时禁用窗口遮罩，动画结束后恢复，提升动画流畅度"

        SettingsSwitch {
            settingKey: "animation_performance"
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_arrow_reset_20_regular"
        title: "恢复默认设置"
        description: "清空本插件的配置文件，所有设置恢复为默认值"

        Button {
            text: "恢复默认设置"
            onClicked: settingsBackend.resetDefaults()
        }
    }
}
