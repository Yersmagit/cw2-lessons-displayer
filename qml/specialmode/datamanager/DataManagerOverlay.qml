import QtQuick 2.15
import "."

// 数据管理弹层：**全屏半透明黑蒙层** + 居中弹出的数据管理页。
// · 只在打开时由 SpecialModeWindow 的 Loader 加载（关闭时 Loader 置空 → 整个组件连同
//   缩略图一起销毁，内存及时回收，用户要求 6）；
// · 点右上角关闭按钮或点四周蒙层都关闭（用户要求 1）；
// · 页面点击 → 转发 pageRequested / historyRequested，由窗口完成切页/导入并关闭。
Item {
    id: root
    objectName: "dataManagerOverlay"

    signal closeRequested()
    signal pageRequested(int index)
    signal historyRequested(string file)

    // 半透明黑蒙层（覆盖整个手写板）
    Rectangle {
        objectName: "dataManagerMask"
        anchors.fill: parent
        color: "#8C000000"
    }
    // 点蒙层 = 关闭（面板在其上方，自己的 MouseArea 会吞掉点击）
    MouseArea {
        objectName: "dataManagerMaskArea"
        anchors.fill: parent
        onClicked: root.closeRequested()
    }

    DataManagerPanel {
        id: panel
        objectName: "dataManagerPanel"
        anchors.centerIn: parent
        onCloseRequested: root.closeRequested()
        onPageActivated: (index) => {
            root.pageRequested(index)
            root.closeRequested()
        }
        onHistoryActivated: (file) => {
            root.historyRequested(file)
            root.closeRequested()
        }
    }
}
