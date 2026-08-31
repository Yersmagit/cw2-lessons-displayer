import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 浮动工具栏的二级菜单（自绘 Item，不依赖 Popup/Overlay，保证任何环境都能显示）：
// - kind="width"：3 个粗细圆（半径=笔划粗细，选中画 1px 外圈边框），填充=选中笔划当前色
// - kind="color"：两排 × 4 色圆（逻辑色名，显示 hex 随深浅色；选中外圈 1px 边框）
// 背景/边框/阴影与工具栏胶囊一致（半透明灰 + 白色 1px 边框 + 阴影）。
// 显示/定位由 SelectionToolbar 通过 visible + x/y 控制（有空间在上方，否则下方）。
Item {
    id: root
    signal widthSelected(int w)
    signal colorSelected(string c)

    property string kind: "width"       // "width" | "color"
    property string title: "粗细"
    property int selectedWidth: 4        // 选中笔划共同粗细（不同=0 → 不亮）
    property string selectedColor: ""    // 选中笔划共同逻辑色（不同=空 → 不亮）

    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color selBorder: lightMode ? "#FF000000" : "#FFFFFFFF"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property int capsuleRadius: 16
    readonly property real cellSize: 34
    readonly property real hitPadX: 7
    readonly property real hitPadY: 4
    readonly property var colorRow1: ["mono", "red", "blue", "green"]
    readonly property var colorRow2: ["orange", "yellow", "cyan", "purple"]

    // 逻辑颜色名 → 当前模式显示 hex（白板浅色=深色/黑，熄屏深色=浅色/白）
    function colorFor(logical) {
        if (logical === "mono") return root.lightMode ? "#000000" : "#FFFFFF"
        var lh = {"red": "#C62828", "blue": "#1565C0", "green": "#2E7D32",
                  "orange": "#EF6C00", "yellow": "#F9A825", "cyan": "#00838F", "purple": "#6A1B9A"}
        var dh = {"red": "#EF5350", "blue": "#42A5F5", "green": "#66BB6A",
                  "orange": "#FFA726", "yellow": "#FFEE58", "cyan": "#4DD0E1", "purple": "#AB47BC"}
        return root.lightMode ? (lh[logical] || "#000000") : (dh[logical] || "#FFFFFF")
    }

    width: 232
    height: root.kind === "width" ? 88 : 132

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
            text: root.title
            color: root.fg
            font.pixelSize: 12
            font.bold: true
        }

        // 粗细：3 圆（半径=笔划粗细），填充=选中笔划当前色（无共同色时用 mono）
        Row {
            visible: root.kind === "width"
            width: parent.width
            readonly property int n: 3
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: [2, 4, 6]
                delegate: OptionCell {
                    innerRadius: modelData + 2
                    fillColor: root.colorFor(root.selectedColor || "mono")
                    selected: root.selectedWidth === modelData
                    MouseArea {
                        anchors.centerIn: parent
                        width: parent.width + root.hitPadX * 2
                        height: parent.height + root.hitPadY * 2
                        onClicked: root.widthSelected(modelData)
                    }
                }
            }
        }

        // 颜色：两排 × 4（选中=共同逻辑色）
        Row {
            visible: root.kind === "color"
            width: parent.width
            readonly property int n: 4
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: root.colorRow1
                delegate: OptionCell {
                    innerRadius: 8
                    fillColor: root.colorFor(modelData)
                    selected: root.selectedColor === modelData
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
            visible: root.kind === "color"
            width: parent.width
            readonly property int n: 4
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: root.colorRow2
                delegate: OptionCell {
                    innerRadius: 8
                    fillColor: root.colorFor(modelData)
                    selected: root.selectedColor === modelData
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
