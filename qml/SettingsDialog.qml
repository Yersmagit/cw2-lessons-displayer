import QtQuick 2.15
import QtQuick.Controls 2.15
import QtQuick.Layouts 1.15
import RinUI

// 设置对话框：复用 RinUI Dialog，模仿主程序 AddWidgetsDialog——左侧侧边栏（基本/特殊模式/高级）
// + 右侧设置页 + 底部关闭；模态自带全屏遮罩。一般模式默认进"基本"页，特殊模式进"特殊模式"页；
// 打开/关闭时禁用/恢复窗口 mask（否则遮罩/对话框被裁剪）。
Dialog {
    id: root
    objectName: "pluginSettingsDialog"  // Python 侧（主程序设置页入口）findChild 用
    title: qsTr("LessonBoard 设置")
    modal: true
    width: 680
    height: 520
    // 底部"关闭"按钮由 RinUI DialogButtonBox 自动渲染（与主程序一致）
    standardButtons: Dialog.Close

    // 三个页面（标题 + 图标 + QML 文件）；"关于"页固定在侧边栏底部，单独用 aboutPage 定义。
    // 特殊模式条目（specialMode:true）的标题/图标在 delegate 里随设备类型动态：
    // 交互智能平板→"手写板模式"+whiteboard 图标；投影设备或其他→"特殊模式"+desktop 图标。
    property var pages: [
        { "title": "基本",     "icon": "ic_fluent_settings_20_regular",    "source": "settings/BasicSettingsPage.qml" },
        { "title": "特殊模式", "specialMode": true, "icon": "ic_fluent_paint_brush_20_regular", "source": "settings/SpecialModeSettingsPage.qml" },
        { "title": "高级",     "icon": "ic_fluent_options_20_regular",     "source": "settings/AdvancedSettingsPage.qml" }
    ]
    property var aboutPage: { "title": "关于", "icon": "ic_fluent_info_20_regular", "source": "settings/AboutSettingsPage.qml" }
    property int currentIndex: 0

    // 打开：按模式选页，禁用 mask 并强制所有窗口置顶；页面延迟到对话框显示且布局稳定后再加载
    // （见 pageDelayTimer 注释），避免首次打开即展开折叠项时说明文字失踪。
    function openDialog() {
        currentIndex = (lessonsBackend.mode === "normal") ? 0 : 1
        sidebarList.currentIndex = currentIndex  // 同步侧边栏高亮（不能依赖绑定，见 sidebarList 注释）
        // 先卸载页面，待对话框显示且 contentItem 布局稳定（pageDelayTimer）后再加载
        pageLoader.active = false
        lessonsBackend.hideWidgetMask()
        lessonsBackend.holdTopmost()
        root.open()
        pageDelayTimer.start()
    }

    // 页面延迟加载定时器：模态 Dialog 首次 open 时 contentItem 可能仍在布局（RinUI
    // SettingExpander 的 header 布局会递归重排，中止后说明文字可能按错误尺寸布局而失踪——
    // 手动"切到其他页再切回"（布局稳定后重建）即正常）。等 80ms 布局稳定后再加载页面。
    Timer {
        id: pageDelayTimer
        interval: 80
        repeat: false
        onTriggered: {
            pageLoader.active = true
        }
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

            // 左侧侧边栏（185 宽）：上方可滚动页面列表，底部固定"关于"项
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
                    // 不能用 currentIndex 绑定（RinUI delegate onClicked 会赋值 view.currentIndex 解除绑定），改为手动同步
                    delegate: ListViewDelegate {
                        Layout.fillWidth: true
                        // 兼容新版 RinUI：ListViewDelegate 已改为标准 ItemDelegate，用 contentItem 自定义内容
                        contentItem: RowLayout {
                            spacing: 8
                            Icon {
                                name: modelData.specialMode
                                    ? (settingsBackend.deviceType === "interactive_panel"
                                        ? "ic_fluent_whiteboard_20_regular"
                                        : "ic_fluent_desktop_20_regular")
                                    : modelData.icon
                                size: 22
                            }
                            Text {
                                wrapMode: Text.NoWrap
                                text: modelData.specialMode
                                    ? (settingsBackend.deviceType === "interactive_panel"
                                        ? "手写板模式"
                                        : modelData.title)
                                    : modelData.title
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                                Layout.rightMargin: 12
                            }
                        }
                        onClicked: {
                            root.currentIndex = index
                            sidebarList.currentIndex = index  // 此处显式保持与 root 一致
                        }
                    }
                }

                // 底部固定"关于"项（不在上方可滚动视图，点击切到关于页）
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

            // 右侧内容区：可上下滚动的设置项视图（无需垂直居中）
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true

                Flickable {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    contentHeight: pageLoader.height
                    clip: true
                    // 内容超出可视高度（可滚动）时显示 RinUI 滚动条（AsNeeded）
                    ScrollBar.vertical: ScrollBar {}

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
