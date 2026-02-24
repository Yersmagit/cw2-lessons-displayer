import QtQuick 2.15
import QtQuick.Window 2.15

Window {
    id: root
    visible: false
    flags: Qt.FramelessWindowHint | Qt.Tool
    color: "transparent"

    // 窗口尺寸和位置绑定到后端属性
    width: lessonsBackend.uiWidth
    height: 54
    x: lessonsBackend.uiX
    y: lessonsBackend.uiY

    // 动画过渡
    Behavior on x {
        NumberAnimation {
            duration: 400
            easing.type: Easing.OutQuint
        }
    }
    Behavior on y {
        NumberAnimation {
            duration: 400
            easing.type: Easing.OutQuint
        }
    }
    Behavior on width {
        NumberAnimation {
            duration: 300
            easing.type: Easing.OutQuint
        }
    }

    Loader {
        id: uiLoader
        objectName: "uiLoader"
        source: "LessonsDisplay.qml"
        asynchronous: false
        anchors.fill: parent  // 使内容填满窗口
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