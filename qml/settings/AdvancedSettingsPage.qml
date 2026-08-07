import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "高级"设置页：两个设置分组（动画性能优化 / 恢复默认设置），各带标题。
// 根为 ColumnLayout（与主程序 SettingsLayout 一致），设置项从上到下依次排开，
// 由 SettingsDialog 的 Flickable 承载滚动。
ColumnLayout {
    id: root
    spacing: 4

    Text {
        typography: Typography.BodyStrong
        text: "高级选项"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_play_20_regular"
        title: "动画性能优化"
        description: "动画播放时禁用部分计算以提高性能，有助于缓解 UI 撕裂问题"

        SettingsSwitch {
            settingKey: "animation_performance"
        }
    }

    Text {
        typography: Typography.BodyStrong
        text: "恢复"
        // 与上方选项保持 8px 间距（ColumnLayout spacing 4 + 额外 4px）
        Layout.topMargin: 4
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_arrow_reset_20_regular"
        title: "恢复默认设置"
        description: "清空本插件的配置文件，所有设置恢复为默认值"

        Button {
            id: resetButton
            text: "恢复默认设置"
            onClicked: {
                settingsBackend.resetDefaults()
                resetFlyout.open()
                resetFlyoutTimer.restart()
            }

            // 恢复成功后按钮下方弹出的提示（含"好的"按钮，3 秒自动关闭）
            Flyout {
                id: resetFlyout
                parent: resetButton
                position: Position.Bottom
                text: "已恢复默认设置"
                buttonBox: [
                    Button {
                        text: "好的"
                        highlighted: true
                        onClicked: {
                            resetFlyout.close()
                            resetFlyoutTimer.stop()
                        }
                    }
                ]
            }

            Timer {
                id: resetFlyoutTimer
                interval: 3000
                onTriggered: resetFlyout.close()
            }
        }
    }
}
