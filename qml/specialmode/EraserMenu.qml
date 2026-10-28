import QtQuick 2.15
import Qt5Compat.GraphicalEffects

// 自绘"清屏"菜单（纯 Item，不依赖 Popup/Overlay）：
// 内含一个白色圆形滑块（无论深浅色均白色），将其从左拖拽到右侧即清空全部笔迹
// （保留旧数据文件并新建空白会话）。轨道为短胶囊沟槽，包裹在滑块外围。
// 背景/边框/阴影与工具栏胶囊一致（半透明灰 + 白色 1px 边框 + 阴影）。
// 显示由 SpecialModeToolbar 通过 visible + x/y 定位控制。
Item {
    id: root
    signal eraseAllRequested()

    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#E6000000" : "#E6FFFFFF"
    readonly property color trackBg: lightMode ? "#26000000" : "#40FFFFFF"
    // 滑块始终白色（深浅色一致），加 1px 深色描边保证在浅色轨道上也清晰可见
    readonly property color thumbColor: "#FFFFFFFF"
    readonly property color thumbBorder: "#40000000"
    readonly property color capsuleColor: lightMode ? "#BBFFFFFF" : "#BB0A0A0A"
    readonly property color capsuleBorder: "#33FFFFFF"
    readonly property int capsuleRadius: 16
    readonly property int thumbSize: 26
    readonly property int trackH: 32
    readonly property int trackGap: 16      // 轨道两端距菜单左右各 16px
    readonly property int thumbGap: (trackH - thumbSize) / 2   // 滑块在轨道内的上下/左右间隙（=3）

    width: 140
    height: 120

    // 阴影与工具栏胶囊一致（半透明灰 13%）
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

    Column {
        anchors.fill: parent
        anchors.margins: 14
        spacing: 10

        Text {
            text: "清屏"
            color: root.fg
            font.pixelSize: 13
            font.bold: true
            anchors.horizontalCenter: parent.horizontalCenter
        }

        // 短胶囊轨道（包裹在滑块外围）+ 白色滑块：拖到最右侧触发清屏
        Item {
            id: slider
            width: parent.width
            height: 36

            // 轨道：水平居中，两端距菜单左右各 trackGap；高 > 滑块，上下包裹滑块
            Rectangle {
                id: track
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                width: root.width - root.trackGap * 2
                height: root.trackH
                radius: height / 2
                color: root.trackBg
            }

            // 滑块：始终白色；初始在轨道最左，左右行程各留 thumbGap（与上下包裹间距一致）
            Rectangle {
                id: thumb
                width: root.thumbSize
                height: root.thumbSize
                radius: width / 2
                color: root.thumbColor
                border.width: 1
                border.color: root.thumbBorder
                x: track.x + root.thumbGap
                y: (slider.height - height) / 2
            }

            MouseArea {
                id: ma
                anchors.fill: parent
                property real grabOffset: 0
                property bool dragging: false
                onPressed: (mouse) => {
                    dragging = true
                    grabOffset = mouse.x - thumb.x
                    thumb.x = clamp(mouse.x - grabOffset)
                }
                onPositionChanged: (mouse) => {
                    if (dragging) thumb.x = clamp(mouse.x - grabOffset)
                }
                onReleased: {
                    if (dragging && thumb.x >= track.x + track.width - thumb.width - root.thumbGap) {
                        root.eraseAllRequested()   // 拖到最右 → 清屏
                    }
                    thumb.x = track.x + root.thumbGap
                    dragging = false
                }
                onCanceled: {
                    thumb.x = track.x + root.thumbGap
                    dragging = false
                }
                function clamp(v) {
                    return Math.max(track.x + root.thumbGap,
                                    Math.min(track.x + track.width - thumb.width - root.thumbGap, v))
                }
            }
        }

        Text {
            text: "向右拖拽滑块以清屏"
            color: root.fg
            font.pixelSize: 10
            opacity: 0.6
            anchors.horizontalCenter: parent.horizontalCenter
        }
    }
}
