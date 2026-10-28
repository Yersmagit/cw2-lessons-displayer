import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 立体图形**测画方式**菜单（由底部工具栏在"形状菜单里选中圆柱 / 圆锥"后弹出，位置同样在按钮上方）：
// - 与其它菜单同风格（半透明底 + 白色 1px 边框 + 阴影）；
// - 两个格子：上 = 该测画方式下的**圆柱/圆锥小图**（ShapeIconPreview，与 Python 侧真实管线
//   同一套投影系数 → 逐像素一致），下 = 名称（正等测 / 斜二测）；
// - 当前测画方式（`whiteboardBackend.solidProjMode`）高亮；
// - 点击 → projSelected(id)，由 SpecialModeToolbar 转给 `whiteboardBackend.setSolidProjMode`。
// - **用户在菜单里选定后菜单不关**：直到开始绘制底面（点画布 → 工具栏 closeMenus）才关掉
//   （用户要求："一旦用户开始绘制底面，就把这个菜单关掉，然后按菜单上的选择使用相应的
//   测画法绘制底面"）。
Item {
    id: root

    signal projSelected(string mode)

    // 小图画的立体图形（由工具栏在弹出前设为所选图形：圆柱 / 圆锥）
    property string figureKind: "cylinder"

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
    readonly property int cellGap: 6
    readonly property int cellH: 54
    readonly property int cellW: 63
    readonly property int items: 2                       // 正等测 / 斜二测
    readonly property int contentH: root.cellH
    readonly property var projItems: whiteboardBackend.solidProjItems
    readonly property string current: whiteboardBackend.solidProjMode

    width: root.cellW * root.items + root.cellGap * (root.items - 1) + 28
    // 14(上) + 内容 + 14(下)
    height: root.contentH + 28

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

    // 测画方式格子：上 = 圆柱小图（该测画方式），下 = 名称；当前项高亮
    component ProjCell: Item {
        id: cell
        property string modeId: ""
        property string modeName: ""
        width: root.cellW
        height: root.cellH
        Rectangle {
            anchors.fill: parent
            radius: 10
            color: cellMa.containsMouse ? root.hoverColor
                 : (root.current === cell.modeId ? root.selectedColor : "transparent")
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        ShapeIconPreview {
            objectName: "projPreview_" + cell.modeId
            anchors.horizontalCenter: parent.horizontalCenter
            y: 6
            width: parent.width - 16
            height: 22
            kind: root.figureKind
            projMode: cell.modeId
            // 线条宽度与**形状菜单小图**完全一致（固定 2px，不跟笔触粗细变 —— 否则笔细时
            // 小图可能看不清，用户要求）；颜色仍随当前笔色/深浅色（与形状菜单同理）
            lineWidth: 2
            lineColor: lessonsBackend.penColor === "mono"
                         ? root.fg : root.colorFor(lessonsBackend.penColor)
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 6
            text: cell.modeName
            color: root.current === cell.modeId ? root.fg : root.dimFg
            font.family: Qt.application.font.family
            font.pixelSize: 12
            font.bold: root.current === cell.modeId
        }
        MouseArea {
            id: cellMa
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.projSelected(cell.modeId)
        }
    }

    // 逻辑颜色名 → 当前模式显示 hex（与 PenMenu.colorFor 一致）
    function colorFor(logical) {
        if (logical === "mono") return root.lightMode ? "#000000" : "#FFFFFF"
        var lightHex = {"red":"#C62828","blue":"#1565C0","green":"#2E7D32",
                        "orange":"#EF6C00","yellow":"#F9A825","cyan":"#00838F","purple":"#6A1B9A"}
        var darkHex = {"red":"#EF5350","blue":"#42A5F5","green":"#66BB6A",
                       "orange":"#FFA726","yellow":"#FFEE58","cyan":"#4DD0E1","purple":"#AB47BC"}
        return root.lightMode ? (lightHex[logical] || "#000000") : (darkHex[logical] || "#FFFFFF")
    }

    Row {
        id: projRow
        objectName: "projRow"
        anchors.horizontalCenter: parent.horizontalCenter
        y: 14
        spacing: root.cellGap
        Repeater {
            model: root.projItems
            delegate: ProjCell {
                required property var modelData
                modeId: modelData.id
                modeName: modelData.name
            }
        }
    }
}
