import QtQuick 2.15
import RinUI

// 工具栏圆形按钮：图标+文字竖排居中，图标占主要部分；无背景色/边框，仅悬停/按下显示半透明圆背景；
// hoverFade=true 时悬停不显示圆背景，改为降低图标/文字不透明度（带过渡动画）。
// 仅响应左键（右键由窗口级 rightClickArea 处理弹出菜单）。颜色/尺寸由使用处（SpecialModeToolbar）传入。
Item {
    id: root
    property string label: ""          // 按钮文字（系统字体）
    property string iconName: ""       // RinUI Fluent 图标名
    property color fg: "#E6000000"     // 图标/文字颜色
    property color bgHover: "#26000000"
    property color bgPressed: "#40000000"
    property bool hoverFade: false      // true：悬停降低内容不透明度（无圆背景）；false：悬停显示圆背景
    property real hoverOpacity: 0.5     // hoverFade 模式下悬停时图标/文字的不透明度
    property int btnSize: 56
    property int iconSize: 24
    property int fontSize: 12
    property bool acceptRightClick: false   // true：右键也接收并发出 rightClicked（用于弹出工具菜单）
    signal clicked()
    signal rightClicked()

    width: btnSize
    height: btnSize

    // 悬停/按下圆形背景（hoverFade 模式不显示）
    Rectangle {
        anchors.fill: parent
        radius: width / 2
        visible: !root.hoverFade
        color: ma.pressed ? root.bgPressed : (ma.containsMouse ? root.bgHover : "transparent")
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    // 图标（上）+ 文字（下），整体居中；hoverFade 模式下悬停时降低整体不透明度
    Column {
        anchors.centerIn: parent
        spacing: 2
        opacity: root.hoverFade && ma.containsMouse ? root.hoverOpacity : 1.0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        Icon {
            name: root.iconName
            size: root.iconSize
            color: root.fg
            Behavior on color { ColorAnimation { duration: 150 } }
            anchors.horizontalCenter: parent.horizontalCenter
        }
        Text {
            text: root.label
            color: root.fg
            Behavior on color { ColorAnimation { duration: 150 } }
            font.family: Qt.application.font.family
            font.pixelSize: root.fontSize
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: root.acceptRightClick ? (Qt.LeftButton | Qt.RightButton) : Qt.LeftButton
        // QML MouseArea 无 onRightClicked 信号，右键也在 onClicked 里用 mouse.button 区分
        onClicked: (mouse) => {
            if (mouse.button === Qt.RightButton) root.rightClicked()
            else root.clicked()
        }
    }
}
