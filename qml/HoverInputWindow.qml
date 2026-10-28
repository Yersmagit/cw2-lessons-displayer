import QtQuick 2.15
import QtQuick.Window 2.15

// 悬停渐隐"输入层"窗口：无任何可见内容（透明），仅供按钮区域承接鼠标点击。
//
// hover_fade 生效时主显示窗口被设为整窗透明输入（鼠标穿透到后方窗口/桌面），本层叠在
// 按钮带上方、mask 只保留按钮区 → 只有按钮带能命中本层；点击坐标交 Python
// （hoverInputBackend.clicked）解析落在哪个按钮并触发对应动作。尺寸/位置/mask 全部由
// Python 维护（含迷你模式 0.7 视觉缩放的按钮带）。
Window {
    id: root
    visible: false
    color: "transparent"
    flags: Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint

    MouseArea {
        id: hitArea
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        hoverEnabled: true
        onClicked: (mouse) => {
            if (typeof hoverInputBackend === "undefined")
                return
            hoverInputBackend.hoverInputClicked(mouse.x, mouse.y, mouse.button)
        }
    }
}
