import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// "关于"设置页：展示插件信息（名称/版本/作者/描述/仓库/许可证）。
// 根为 ColumnLayout（与主程序 SettingsLayout 一致），由 SettingsDialog 的 Flickable 承载滚动。
// 数据由 SettingsBackend 从 cwplugin.json 读取（与发版流程同步，不硬编码）。
ColumnLayout {
    id: root
    spacing: 4

    Text {
        typography: Typography.BodyStrong
        text: "关于"
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_info_20_regular"
        title: settingsBackend.pluginName
        description: settingsBackend.pluginDescription

        Text {
            color: Theme.currentTheme.colors.textSecondaryColor
            text: "v" + settingsBackend.pluginVersion
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_person_20_regular"
        title: "作者"
        description: settingsBackend.pluginAuthor
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_link_20_regular"
        title: "仓库"
        description: settingsBackend.pluginUrl

        Button {
            text: "打开"
            icon.name: "ic_fluent_open_20_regular"
            onClicked: Qt.openUrlExternally(settingsBackend.pluginUrl)
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_comment_20_regular"
        title: "反馈"
        description: "报告问题或提出建议（GitHub Issue）"

        Button {
            text: "提交 Issue"
            icon.name: "ic_fluent_open_20_regular"
            onClicked: Qt.openUrlExternally(settingsBackend.pluginUrl + "/issues/new")
        }
    }

    SettingCard {
        Layout.fillWidth: true
        icon.name: "ic_fluent_document_20_regular"
        title: "许可证"
        description: "MIT License"
    }
}
