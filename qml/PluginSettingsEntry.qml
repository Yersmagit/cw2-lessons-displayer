import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import RinUI
import ClassWidgets.Plugins

// 主程序设置页的"插件设置"入口页（register_settings_page 注册，显示于"插件"分组下）。
// 页面只提供一个"打开插件设置对话框"的入口卡片。卡片布局与主程序"小组件"设置页顶部
// 的 Introduction 组件（pages/settings/General/Widgets.qml → ClassWidgets.Components/Introduction.qml）
// 完全一致（Frame 圆角卡片：左侧图 + 右侧标题/说明 + 右下角 flat+highlighted 按钮）；
// 仅把左侧 logo（本插件 icon.png）的尺寸比 Introduction 固定区（最大 200×150）调小一点。
// 点击右下角"LessonBoard 设置"经 backend（本插件实例）打开插件设置对话框。
PluginPage {
    id: root
    pluginId: "com.yersmagit.lessonsdisplayer"
    title: qsTr("LessonBoard")

    ColumnLayout {
        Layout.fillWidth: true
        spacing: 12

        // 同 Introduction 组件结构（Frame + RowLayout + 左图/右文/右下按钮）
        Frame {
            Layout.fillWidth: true
            padding: 24

            RowLayout {
                anchors.fill: parent
                spacing: 24

                // 左侧 logo（本插件 icon.png，比 Introduction 固定 200×150 略小）
                Image {
                    Layout.alignment: Qt.AlignCenter
                    Layout.preferredWidth: 120
                    Layout.preferredHeight: 104
                    Layout.maximumWidth: 120
                    Layout.maximumHeight: 104
                    fillMode: Image.PreserveAspectFit
                    source: Qt.resolvedUrl("../icon.png")
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.alignment: Qt.AlignHCenter
                    spacing: 12

                    Text {
                        Layout.fillWidth: true
                        typography: Typography.BodyLarge
                        text: qsTr("LessonBoard 课程灵动条 & 手写板")
                    }
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("管理本插件小组件的显示与层级，以及手写板模式等选项。\n插件设置也可以在小组件右键菜单中选择“设置”打开。")
                    }
                    Button {
                        flat: true
                        highlighted: true
                        Layout.alignment: Qt.AlignRight
                        icon.name: "ic_fluent_arrow_right_20_regular"
                        text: qsTr("LessonBoard 设置")
                        onClicked: {
                            if (backend && typeof backend.openSettingsDialog === "function")
                                backend.openSettingsDialog()
                        }
                    }
                }
            }
        }
    }
}
