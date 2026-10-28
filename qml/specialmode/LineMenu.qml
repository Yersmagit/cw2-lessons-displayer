import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 线型菜单（从"形状菜单 > 线"页整体搬出来，由底部工具栏的**直线按钮**弹出）：
// - 与笔/橡皮/形状菜单同风格（半透明底 + 白色 1px 边框 + 阴影）；
// - **两列**网格（列间距 6px；单元格宽 = 内容宽平分后再各减 2px，网格整体居中）；
// - 每格上=线形预览（LineStylePreview 自绘，图案参数与 Python 侧 `_draw_shape_line` 一致）、
//   下=名称；当前线型（`lessonsBackend.lineStyle`）高亮；
// - 点击某项 → lineSelected(id)，由 SpecialModeToolbar 转给 `lessonsBackend.setLineStyle(id)`。
Item {
    id: root

    signal lineSelected(string style)

    // 深浅色（与工具栏一致：白板=浅色）
    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color dimFg: lightMode ? "#61000000" : "#61FFFFFF"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property color hoverColor: lightMode ? "#0A000000" : "#20FFFFFF"
    readonly property color selectedColor: lightMode ? "#14000000" : "#28FFFFFF"
    readonly property int capsuleRadius: 16

    readonly property int rowSpacing: 2
    readonly property int colCount: 2
    readonly property int cellGap: 6
    readonly property int cellH: 54
    // 单元格宽度：内容宽平分后再**各减 2px**，余量均分两侧 → 网格整体居中
    readonly property int contentW: root.width - 28
    readonly property int cellW: Math.floor((root.contentW - root.cellGap * (root.colCount - 1))
                                            / root.colCount) - 2
    readonly property int rows: Math.ceil(Math.max(1, lineItems.length) / root.colCount)
    readonly property int contentH: root.rows * root.cellH + (root.rows - 1) * root.rowSpacing
    readonly property var lineItems: lessonsBackend.lineStyleItems

    // 预览用的线宽：跟随笔的粗细，但至少 3px（细线在菜单里看不清）
    readonly property real previewW: Math.max(3, lessonsBackend.penWidth)
    // 预览颜色：跟随笔的颜色（逻辑色名 → 当前模式显示色）
    readonly property color previewColor: lessonsBackend.penColor === "mono"
                                           ? fg : root.colorFor(lessonsBackend.penColor)

    width: 236
    // 14(上) + 内容 + 14(下)
    height: root.contentH + 28

    // 逻辑颜色名 → 当前模式显示 hex（与 PenMenu.colorFor 一致）
    function colorFor(logical) {
        if (logical === "mono") return root.lightMode ? "#000000" : "#FFFFFF"
        var lightHex = {"red":"#C62828","blue":"#1565C0","green":"#2E7D32",
                        "orange":"#EF6C00","yellow":"#F9A825","cyan":"#00838F","purple":"#6A1B9A"}
        var darkHex = {"red":"#EF5350","blue":"#42A5F5","green":"#66BB6A",
                       "orange":"#FFA726","yellow":"#FFEE58","cyan":"#4DD0E1","purple":"#AB47BC"}
        return root.lightMode ? (lightHex[logical] || "#000000") : (darkHex[logical] || "#FFFFFF")
    }

    // 阴影 + 背景（与工具栏胶囊一致）
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

    // 线型格子：上=线形预览（Canvas 自绘），下=名称；格子高亮=当前线型
    component LineCell: Item {
        id: cell
        property string styleId: ""
        property string styleName: ""
        width: root.cellW
        height: root.cellH
        Rectangle {
            anchors.fill: parent
            radius: 10
            color: cellMa.containsMouse ? root.hoverColor
                 : (lessonsBackend.lineStyle === cell.styleId ? root.selectedColor : "transparent")
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        LineStylePreview {
            anchors.horizontalCenter: parent.horizontalCenter
            y: 6
            width: parent.width - 16
            height: 22
            styleId: cell.styleId
            lineWidth: root.previewW
            lineColor: root.previewColor
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            text: cell.styleName
            color: lessonsBackend.lineStyle === cell.styleId ? root.fg : root.dimFg
            font.family: Qt.application.font.family
            font.pixelSize: 12
            font.bold: lessonsBackend.lineStyle === cell.styleId
        }
        MouseArea {
            id: cellMa
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.lineSelected(cell.styleId)
        }
    }

    Grid {
        id: lineGrid
        objectName: "lineGrid"
        x: (parent.width - width) / 2
        y: 14
        columns: root.colCount
        columnSpacing: root.cellGap
        rowSpacing: root.rowSpacing
        Repeater {
            model: root.lineItems
            delegate: LineCell {
                required property var modelData
                styleId: modelData.id
                styleName: modelData.name
            }
        }
    }
}
