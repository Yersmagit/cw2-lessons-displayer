import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 自绘笔工具菜单（纯 Item，不依赖 Popup/Overlay，保证任何环境都能显示）：
// - "粗细"：3 个圆，半径 = 笔划粗细(2/4/6px)，选中在圆外画 1px 边框（距内圆 2px）
// - "颜色"：两排 × 4 色圆（半径 6px），浅色模式深色 / 深色模式浅色，白/黑随模式
// 布局：每排第一个与最后一个竖直对齐，中间选项平均分布。
// 背景/边框/阴影与工具栏胶囊一致（半透明灰 + 白色 1px 边框 + 阴影）。
// 显示由 SpecialModeToolbar 通过 visible + x/y 定位控制。
Item {
    id: root
    signal widthSelected(int w)
    signal colorSelected(string color)

    // 深浅色（与工具栏一致：白板=浅色）
    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color selBorder: lightMode ? "#FF000000" : "#FFFFFFFF"
    // 背景/边框与工具栏胶囊一致（随模式：浅色白 73% / 深色黑 73% + 白色 1px 边框）
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property int capsuleRadius: 16
    // 单元格放大（圆更大）+ 间距相应缩小 → 各圆排列更紧凑
    readonly property real cellSize: 34
    // 可触发区扩展：视觉不变，命中区向外扩（横向 7px / 纵向 4px，均不越到相邻格）
    readonly property real hitPadX: 7
    readonly property real hitPadY: 4
    // 颜色选项：逻辑颜色名（白/黑=mono + 7 彩色）；显示 hex 由 colorFor 按模式映射
    readonly property var colorRow1: ["mono", "red", "blue", "green"]
    readonly property var colorRow2: ["orange", "yellow", "cyan", "purple"]

    // 逻辑颜色名 → 当前模式显示 hex（白板浅色=深色/黑，熄屏深色=浅色/白）
    function colorFor(logical) {
        if (logical === "mono") return root.lightMode ? "#000000" : "#FFFFFF"
        var lightHex = {"red":"#C62828","blue":"#1565C0","green":"#2E7D32",
                        "orange":"#EF6C00","yellow":"#F9A825","cyan":"#00838F","purple":"#6A1B9A"}
        var darkHex = {"red":"#EF5350","blue":"#42A5F5","green":"#66BB6A",
                       "orange":"#FFA726","yellow":"#FFEE58","cyan":"#4DD0E1","purple":"#AB47BC"}
        return root.lightMode ? (lightHex[logical] || "#000000") : (darkHex[logical] || "#FFFFFF")
    }

    width: 232
    height: 198

    // 阴影 + 背景（阴影与工具栏胶囊一致：半透明灰 13%）
    DropShadow {
        anchors.fill: parent
        source: menuBgRect
        radius: 20
        samples: 40
        color: "#22000000"
        transparentBorder: true
    }
    Rectangle {
        id: menuBgRect
        anchors.fill: parent
        radius: root.capsuleRadius
        color: root.capsuleColor
        border.width: 1
        border.color: root.capsuleBorder
    }

    // 单个选项：内圆 + 选中外圈
    component OptionCell: Item {
        property real innerRadius: 6
        property color fillColor: "transparent"
        property bool selected: false
        width: root.cellSize
        height: root.cellSize
        Rectangle {
            anchors.centerIn: parent
            width: innerRadius * 2
            height: innerRadius * 2
            radius: innerRadius
            color: fillColor
        }
        Rectangle {
            anchors.centerIn: parent
            width: (innerRadius + 5) * 2
            height: (innerRadius + 5) * 2
            radius: innerRadius + 5
            color: "transparent"
            border.width: selected ? 2 : 0
            border.color: selected ? root.selBorder : "transparent"
        }
    }

    Column {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 8

        Text {
            text: "粗细"
            color: root.fg
            font.pixelSize: 12
            font.bold: true
        }
        Row {
            width: parent.width
            readonly property int n: 3
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: [2, 4, 6]
                delegate: OptionCell {
                    innerRadius: modelData + 2
                    fillColor: root.colorFor(lessonsBackend.penColor)
                    selected: lessonsBackend.penWidth === modelData
                    MouseArea {
                        anchors.centerIn: parent
                        width: parent.width + root.hitPadX * 2
                        height: parent.height + root.hitPadY * 2
                        onClicked: root.widthSelected(modelData)
                    }
                }
            }
        }

        Text {
            text: "颜色"
            color: root.fg
            font.pixelSize: 12
            font.bold: true
        }
        Row {
            width: parent.width
            readonly property int n: 4
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: root.colorRow1
                delegate: OptionCell {
                    innerRadius: 8
                    fillColor: root.colorFor(modelData)
                    selected: lessonsBackend.penColor === modelData
                    MouseArea {
                        anchors.centerIn: parent
                        width: parent.width + root.hitPadX * 2
                        height: parent.height + root.hitPadY * 2
                        onClicked: root.colorSelected(modelData)
                    }
                }
            }
        }
        Row {
            width: parent.width
            readonly property int n: 4
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: root.colorRow2
                delegate: OptionCell {
                    innerRadius: 8
                    fillColor: root.colorFor(modelData)
                    selected: lessonsBackend.penColor === modelData
                    MouseArea {
                        anchors.centerIn: parent
                        width: parent.width + root.hitPadX * 2
                        height: parent.height + root.hitPadY * 2
                        onClicked: root.colorSelected(modelData)
                    }
                }
            }
        }
    }
}
