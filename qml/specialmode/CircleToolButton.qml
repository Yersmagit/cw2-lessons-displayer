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
    property bool showExpandIndicator: false   // 显示展开指示器（小 chevron，位于上方图标右侧）
    property bool expandIndicatorRotated: false // 指示器旋转 180°（二级菜单已展开，提示可收回）
    property int expandIndicatorSize: 14        // 展开指示器尺寸（略小于主图标）
    property real expandGap: 0.5                // 主图标与展开指示器间距（紧凑）
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

    // 图标（上）+ 文字（下），整体居中并下移 1px（视觉对齐）；hoverFade 模式悬停时降低不透明度
    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: 1
        spacing: 2
        opacity: root.hoverFade && ma.containsMouse ? root.hoverOpacity : 1.0
        Behavior on opacity { NumberAnimation { duration: 120 } }
        // 上方图标行：主图标 + 可选展开指示器（chevron）。
        // 指示器显示/隐藏时：容器宽度动画 → 主图标随容器整体水平平移给指示器腾位置；
        // 指示器透明度渐变显示/隐藏（visible 跟随 opacity，淡入后出现、淡出到 0 后隐藏）；
        // 旋转随菜单展开状态（180°）。
        Item {
            id: iconRow
            anchors.horizontalCenter: parent.horizontalCenter
            // 有指示器时整体右移一点点（图标大在左，组合略偏右视觉重心更居中）；无指示器不偏移
            anchors.horizontalCenterOffset: root.showExpandIndicator ? 2 : 0
            width: root.iconSize + (root.showExpandIndicator ? (root.expandGap + root.expandIndicatorSize) : 0)
            height: root.iconSize
            Behavior on width { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
            Icon {
                name: root.iconName
                size: root.iconSize
                color: root.fg
                Behavior on color { ColorAnimation { duration: 150 } }
                x: 0
                anchors.verticalCenter: parent.verticalCenter
            }
            Icon {
                name: "ic_fluent_chevron_up_20_regular"
                size: root.expandIndicatorSize
                x: root.iconSize + root.expandGap
                anchors.verticalCenter: parent.verticalCenter
                opacity: root.showExpandIndicator ? 1 : 0
                visible: opacity > 0.01   // 跟随透明度动画（淡入后可见、淡出到 0 后隐藏）
                rotation: root.expandIndicatorRotated ? 180 : 0
                color: root.fg
                Behavior on opacity { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
                Behavior on rotation { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
            }
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
