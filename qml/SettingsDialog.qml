import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// 设置对话框：复用 RinUI Dialog，布局模仿主程序"添加小组件"（AddWidgetsDialog）界面。
// - 模态对话框（modal:true），自带全屏黑色半透明遮罩（Overlay.modal）。
// - 标题 "Lessons Displayer 设置"；左侧侧边栏（185 宽，ListView + ListViewDelegate）
//   切换"基本 / 特殊模式 / 高级"三个页面；右侧为对应页面的设置项（SettingCard，自动保存）；
//   底部 footer 为"关闭"按钮。
// - 一般模式打开默认进入"基本"页；特殊模式打开默认进入"特殊模式"页。
// - 打开/关闭时通过 lessonsBackend 的 mask 引用计数禁用/恢复窗口 mask（否则遮罩/对话框
//   会被窗口 mask 裁剪）。
Dialog {
    id: root
    title: qsTr("Lessons Displayer 设置")
    modal: true
    width: 680
    height: 520
    // 底部"关闭"按钮：与主程序"添加小组件"（AddWidgetsDialog）一致，
    // 由 RinUI DialogButtonBox 自动渲染（位置/样式一致）。
    standardButtons: Dialog.Close

    // 三个页面：侧边栏标题 + 图标 + 对应 QML 文件（相对本文件路径）。
    // "关于"页固定在侧边栏底部（不参与滚动），单独用 aboutPage 定义。
    property var pages: [
        { "title": "基本",     "icon": "ic_fluent_settings_20_regular",    "source": "settings/BasicSettingsPage.qml" },
        { "title": "特殊模式", "icon": "ic_fluent_paint_brush_20_regular", "source": "settings/SpecialModeSettingsPage.qml" },
        { "title": "高级",     "icon": "ic_fluent_options_20_regular",     "source": "settings/AdvancedSettingsPage.qml" }
    ]
    property var aboutPage: { "title": "关于", "icon": "ic_fluent_info_20_regular", "source": "settings/AboutSettingsPage.qml" }
    property int currentIndex: 0

    // 打开：一般模式 → "基本"页；特殊模式 → "特殊模式"页；禁用 mask 并强制所有窗口置顶。
    // 注意：宿主窗口 winId 早已存在，open() 前置顶即可生效。
    // 每次打开都强制 Loader 重新加载页面（active 切换），避免显示上次离开时残留的
    // 页面实例/滚动位置——即使 currentIndex 与上次相同也要重新创建页面。
    function openDialog() {
        currentIndex = (lessonsBackend.mode === "normal") ? 0 : 1
        sidebarList.currentIndex = currentIndex  // 同步侧边栏高亮（不能依赖绑定，见 sidebarList 注释）
        // 强制重新加载当前 source 的页面（销毁旧实例并重建，source 绑定保持不变）
        pageLoader.active = false
        pageLoader.active = true
        lessonsBackend.hideWidgetMask()
        lessonsBackend.holdTopmost()
        root.open()
    }

    // 关闭后恢复窗口 mask 与窗口层级，并重置页面索引（下次打开按模式重新选择）
    onClosed: {
        lessonsBackend.showWidgetMask()
        lessonsBackend.releaseTopmost()
        currentIndex = 0
        sidebarList.currentIndex = 0  // 同步侧边栏高亮
    }

    contentItem: ColumnLayout {
        spacing: 12

        // 标题
        Text {
            Layout.fillWidth: true
            typography: Typography.Subtitle
            text: root.title
        }

        // 侧边栏 + 内容区（模仿主程序 AddWidgetsDialog）
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 16

            // 左侧侧边栏：185 宽，上方为可滚动页面列表（基本/特殊模式/高级），
            // 底部固定"关于"项（不参与滚动，始终可见）
            ColumnLayout {
                Layout.preferredWidth: 185
                Layout.maximumWidth: 185
                Layout.fillHeight: true
                spacing: 0

                // 上方可滚动视图：前三个页面按钮（滚动区高度 = 侧边栏总高 - 底部"关于"项占用）
                ListView {
                    id: sidebarList
                    objectName: "sidebarList"
                    clip: true
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    model: root.pages
                    // 注意：不能用 currentIndex: root.currentIndex 绑定——RinUI ListViewDelegate
                    // 的 onClicked 内部会直接赋值 ListView.view.currentIndex，这会解除该绑定，
                    // 导致侧边栏高亮固定在上次点击的位置、不再跟随 root.currentIndex。
                    // 因此改为在 openDialog()/onClosed()/delegate onClicked 中手动同步。
                    delegate: ListViewDelegate {
                        Layout.fillWidth: true
                        leftArea: Icon {
                            icon: modelData.icon
                            size: 22
                        }
                        middleArea: [
                            Text {
                                wrapMode: Text.NoWrap
                                text: modelData.title
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                                Layout.rightMargin: 12
                            }
                        ]
                        onClicked: {
                            root.currentIndex = index
                            sidebarList.currentIndex = index  // ListViewDelegate 内部已设置，此处显式保持与 root 一致
                        }
                    }
                }

                // 底部固定"关于"项：视觉与 ListViewDelegate 一致（背景 + 高亮指示条），
                // 不在上方的可滚动视图中，点击切到"关于"页（currentIndex == pages.length）
                Item {
                    id: aboutItem
                    objectName: "aboutItem"
                    Layout.fillWidth: true
                    Layout.preferredHeight: contents.implicitHeight + 20

                    property bool highlighted: root.currentIndex === root.pages.length
                    property bool hovered: aboutMouse.containsMouse

                    Rectangle {
                        anchors.fill: parent
                        anchors.leftMargin: 5
                        anchors.rightMargin: 5
                        anchors.topMargin: 3
                        radius: Theme.currentTheme.appearance.buttonRadius
                        color: aboutMouse.pressed
                            ? Theme.currentTheme.colors.subtleTertiaryColor
                            : (aboutItem.highlighted || aboutItem.hovered)
                                ? Theme.currentTheme.colors.subtleSecondaryColor
                                : Theme.currentTheme.colors.subtleColor

                        Behavior on color { ColorAnimation { duration: Utils.appearanceSpeed; easing.type: Easing.InOutQuart } }
                    }

                    // 选择指示器（与 ListViewDelegate 内 Indicator 一致）
                    Rectangle {
                        id: aboutIndicator
                        width: 3
                        height: contents.implicitHeight + 20 - 23
                        radius: 10
                        color: Theme.currentTheme.colors.primaryColor
                        anchors.left: parent.left
                        anchors.leftMargin: 5
                        anchors.verticalCenter: parent.verticalCenter
                        opacity: aboutItem.highlighted ? 1.0 : 0.0
                        Behavior on opacity { NumberAnimation { duration: Utils.animationSpeed; easing.type: Easing.OutQuad } }
                    }

                    RowLayout {
                        id: contents
                        anchors.fill: parent
                        anchors.leftMargin: 5 + 11
                        anchors.rightMargin: 5
                        anchors.topMargin: 3
                        spacing: 8

                        Icon {
                            icon: root.aboutPage.icon
                            size: 22
                        }
                        Text {
                            wrapMode: Text.NoWrap
                            text: root.aboutPage.title
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                            Layout.rightMargin: 12
                        }
                    }

                    MouseArea {
                        id: aboutMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            root.currentIndex = root.pages.length
                            sidebarList.currentIndex = -1  // 取消上方列表高亮，仅"关于"高亮
                        }
                    }
                }
            }

            // 右侧内容区：可上下滚动的视图（模仿主程序 WidgetSettingsDialog），
            // 设置项从上到下依次排开，无需垂直居中
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentHeight: pageLoader.height
                    clip: true

                    Loader {
                        id: pageLoader
                        objectName: "pageLoader"
                        width: parent.width
                        source: root.currentIndex >= root.pages.length
                            ? root.aboutPage.source
                            : root.pages[root.currentIndex].source
                    }
                }
            }
        }
    }
}
