import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: root
    visible: false
    // flags 绑定到模式，特殊模式时置顶
    flags: {
        var baseFlags = Qt.FramelessWindowHint | Qt.Tool;
        if (lessonsBackend.mode !== "normal") {
            return baseFlags | Qt.WindowStaysOnTopHint;
        } else {
            return baseFlags;
        }
    }
    color: "transparent"

    // 窗口始终全屏且不透明
    x: 0
    y: 0
    width: Screen.width
    height: Screen.height

    // 背景层（仅在特殊模式下显示，带淡入淡出动画和颜色动画）
    Rectangle {
        id: backgroundLayer
        anchors.fill: parent
        color: lessonsBackend.mode === "whiteboard" ? "white" : (lessonsBackend.mode === "blackboard" ? "black" : "transparent")
        opacity: 0
        z: 0

        Behavior on color {
            ColorAnimation { duration: 300; easing.type: Easing.OutCubic }
        }
        Behavior on opacity {
            NumberAnimation { duration: 300; easing.type: Easing.OutCubic }
        }

        // 当模式变化时，根据模式设置透明度
        states: [
            State {
                name: "normal"
                when: lessonsBackend.mode === "normal"
                PropertyChanges { target: backgroundLayer; opacity: 0 }
            },
            State {
                name: "whiteboard"
                when: lessonsBackend.mode === "whiteboard"
                PropertyChanges { target: backgroundLayer; opacity: 1 }
            },
            State {
                name: "blackboard"
                when: lessonsBackend.mode === "blackboard"
                PropertyChanges { target: backgroundLayer; opacity: 1 }
            }
        ]
    }

    Loader {
        id: uiLoader
        objectName: "uiLoader"
        source: "LessonsDisplay.qml"
        asynchronous: false
        // 根据模式动态绑定位置和宽度
        x: lessonsBackend.mode === "normal" ? lessonsBackend.uiX : 4
        y: lessonsBackend.mode === "normal" ? lessonsBackend.uiY : 4
        width: lessonsBackend.mode === "normal" ? lessonsBackend.uiWidth : parent.width - 8
        height: 54
        opacity: lessonsBackend.uiOpacity  // 透明度绑定后端属性，实现淡入淡出
        z: 1

        Behavior on x { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }
        Behavior on y { NumberAnimation { duration: 400; easing.type: Easing.OutQuint } }
        Behavior on width { NumberAnimation { duration: 300; easing.type: Easing.OutQuint } }
        Behavior on height { NumberAnimation { duration: 300; easing.type: Easing.OutQuint } }
        Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }

        onStatusChanged: {
            console.log("Loader status changed:", status)
            if (status === Loader.Ready) {
                console.log("Loader ready, item:", item)
                root.uiReady()
            } else if (status === Loader.Error) {
                console.log("Loader error:", errorString())
                root.uiReady()
            }
        }
    }

    function checkLoader() {
        if (uiLoader.status === Loader.Ready) {
            root.uiReady()
        } else if (uiLoader.status === Loader.Error) {
            console.log("Loader error:", uiLoader.errorString())
            root.uiReady()
        } else {
            Qt.callLater(checkLoader)
        }
    }

    Component.onCompleted: {
        console.log("FullScreenWindow completed")
        Qt.callLater(checkLoader)
    }

    signal uiReady()
}