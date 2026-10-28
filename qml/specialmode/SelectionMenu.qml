import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 浮动工具栏的二级菜单（自绘 Item，不依赖 Popup/Overlay，保证任何环境都能显示）：
// - kind="width"：4 个粗细圆（半径=笔划粗细，选中画 1px 外圈边框），填充=选中笔划当前色
// - kind="color"：两排 × 4 色圆（逻辑色名，显示 hex 随深浅色；选中外圈 1px 边框）
// - kind="linestyle"：各种线型（仅“选中项全是形状线”时由浮动工具栏弹出），
//   每项用共用组件 LineStylePreview 把线形直接画出来 + 名称，选中项高亮
// 背景/边框/阴影与工具栏胶囊一致（半透明灰 + 白色 1px 边框 + 阴影）。
// 显示/定位由 SelectionToolbar 通过 visible + x/y 控制（有空间在上方，否则下方）。
Item {
    id: root
    signal widthSelected(real w)
    signal colorSelected(string c)
    signal lineStyleSelected(string style)

    property string kind: "width"       // "width" | "color" | "linestyle"
    property string title: "粗细"
    property real selectedWidth: 3.0     // 选中笔划共同粗细（不同=0 → 不亮）
    property string selectedColor: ""    // 选中笔划共同逻辑色（不同=空 → 不亮）
    // 线型页：两列网格的行高/间距（高度按行数算，与其它两页不同）
    readonly property int lineCellH: 50
    readonly property int lineCellGap: 6
    readonly property int lineRowSpacing: 2
    readonly property int lineColCount: 2
    readonly property int lineContentW: 232 - 16 * 2
    readonly property int lineCellW: Math.floor((root.lineContentW - root.lineCellGap
                                                 * (root.lineColCount - 1))
                                                / root.lineColCount) - 2

    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color selBorder: lightMode ? "#FF000000" : "#FFFFFFFF"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property color hoverColor: lightMode ? "#0A000000" : "#20FFFFFF"
    readonly property color selectedColor2: lightMode ? "#14000000" : "#28FFFFFF"
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
    // 高度：粗细页 88 / 颜色页 132 / 线型页按**实际行数**算（两列 → 行数 = ⌈n/2⌉）
    readonly property int lineCount: Math.max(1, lessonsBackend.lineStyleItems.length)
    readonly property int lineRows: Math.ceil(root.lineCount / root.lineColCount)
    height: root.kind === "width" ? 88
          : root.kind === "color" ? 132
          : 16 * 2 + 16 + 8 + root.lineRows * root.lineCellH
            + (root.lineRows - 1) * root.lineRowSpacing

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

        // 粗细：4 圆（半径=笔划粗细），填充=选中笔划当前色（无共同色时用 mono）
        Row {
            visible: root.kind === "width"
            width: parent.width
            readonly property int n: 4
            spacing: (width - n * root.cellSize) / (n - 1)
            Repeater {
                model: [2, 3, 4.5, 6]
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

        // 线型：**两列**网格，每格上=线形预览（把线形直接画出来）、下=名称。
        // 仅在“选中项全是形状线”时由浮动工具栏弹出（含手绘笔迹/图形的混选不显示该项）。
        // 外面包一层普通 Item：Grid 不能直接做 Column 的子项再用 anchors 居中。
        Item {
            visible: root.kind === "linestyle"
            width: parent.width
            height: root.lineRows * root.lineCellH + (root.lineRows - 1) * root.lineRowSpacing
            Grid {
                columns: root.lineColCount
                columnSpacing: root.lineCellGap
                rowSpacing: root.lineRowSpacing
                anchors.horizontalCenter: parent.horizontalCenter
                Repeater {
                    model: lessonsBackend.lineStyleItems
                    delegate: Item {
                        required property var modelData
                        width: root.lineCellW
                        height: root.lineCellH
                        Rectangle {
                            anchors.fill: parent
                            radius: 8
                            color: lineMa.containsMouse ? root.hoverColor
                                 : (whiteboardBackend.selectionLineStyle === modelData.id
                                    ? root.selectedColor2 : "transparent")
                            Behavior on color { ColorAnimation { duration: 120 } }
                        }
                        LineStylePreview {
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: 6
                            width: parent.width - 12
                            height: 20
                            styleId: modelData.id
                            lineWidth: 3
                            lineColor: root.fg
                        }
                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom
                            anchors.bottomMargin: 5
                            text: modelData.name
                            color: root.fg
                            font.family: Qt.application.font.family
                            font.pixelSize: 12
                            font.bold: whiteboardBackend.selectionLineStyle === modelData.id
                        }
                        MouseArea {
                            id: lineMa
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: root.lineStyleSelected(modelData.id)
                        }
                    }
                }
            }
        }
    }
}
