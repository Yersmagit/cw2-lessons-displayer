import QtQuick 2.15

// 文件管理页「最近打开」里的单个页面条目（对齐设计稿）：
// 格子 152×122、圆角 8；缩略图 128×80、内缩 12、圆角 4；缩略图下方 13px 标题水平居中。
// 当前页：格子 15% 底色 + 缩略图 2px 黑/白描边 + 标题加粗；其余页 1px 15% 淡描边。
// 只在本页打开时被创建（面板整个由 Loader 按需加载），`cache: false` → 关闭后不留 QML 图片缓存。
Item {
    id: root

    property string title: ""
    property string source: ""
    property bool current: false        // 手写板当前页 → 2px 黑/白描边 + 底色 + 标题加粗
    property int thumbW: 128
    property int thumbH: 80
    property int pad: 12                // 缩略图在格子内的内缩
    property int tileRadius: 8
    property int thumbRadius: 8
    // 缩略图渐显时长（毫秒）
    property int fadeMs: 250
    // 加载排队：由面板按「修改时间更晚 → 更早」给的名次算出启动延迟（ms），到点才开始真正加载
    property int loadDelay: 0
    property bool loadReady: loadDelay <= 0
    // 标题区（缩略图下方）：间隙 6 + 高 18 → 格子总高 12 + 80 + 30 = 122（设计稿）
    readonly property int titleGap: 6
    readonly property int titleH: 18
    readonly property int titleBlockH: 30

    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#000000" : "#FFFFFF"
    readonly property color pickColor: lightMode ? "#1A000000" : "#26F2F2F2"
    readonly property color hoverColor: lightMode ? "#0D000000" : "#1AFFFFFF"
    readonly property color thumbFill: lightMode ? "#26A6A6A6" : "#26000000"
    readonly property color thumbStroke: lightMode ? "#26121212" : "#26F2F2F2"
    // 边框：当前页 = 2px 黑/白；其他页 = 1px 15%
    readonly property int frameBorderWidth: root.current ? 2 : 1
    readonly property color frameBorderColor: root.current ? root.fg : root.thumbStroke

    signal activated()

    implicitWidth: 152
    implicitHeight: root.pad + root.thumbH + root.titleBlockH

    // 选中 / 悬停底色（当前页 15%，悬停更淡）
    Rectangle {
        anchors.fill: parent
        radius: root.tileRadius
        color: root.current ? root.pickColor
                            : (ma.containsMouse ? root.hoverColor : "transparent")
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    // 缩略图框
    Rectangle {
        id: frame
        x: root.pad
        y: root.pad
        width: root.thumbW
        height: root.thumbH
        radius: root.thumbRadius
        color: root.thumbFill
        border.width: root.frameBorderWidth
        border.color: root.frameBorderColor
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Image {
            objectName: "dataManagerThumb"
            anchors.fill: parent
            anchors.margins: 2
            // 延迟到点才真正开始加载 → 越新的缩略图越先加载
            source: root.loadReady ? root.source : ""
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: false          // 关闭面板即释放（资源只在打开时占用）

            // 加载完成 → **透明度渐显**（250ms OutCubic）；只渐显一次，
            // 之后缩略图被刷新（换 URL 重载）时保持不透明，不会每次闪一下。
            property bool fadedIn: false
            opacity: fadedIn ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: root.fadeMs; easing.type: Easing.OutCubic } }

            function checkFaded() {
                if (status === Image.Ready)
                    fadedIn = true
            }
            onStatusChanged: checkFaded()
            Component.onCompleted: checkFaded()
        }
    }

    // 排队延迟到点 → 放行加载（问一次只跑一次，之后不再重算）
    Timer {
        interval: root.loadDelay
        running: root.loadDelay > 0 && !root.loadReady
        onTriggered: root.loadReady = true
    }

    // 标题（页码 / 修改时间）：缩略图下方，水平居中，13px
    Text {
        id: titleText
        objectName: "dataManagerTileTitle"
        x: 0
        y: root.pad + root.thumbH + root.titleGap
        width: root.width
        height: root.titleH
        text: root.title
        color: root.fg
        font.family: Qt.application.font.family
        font.pixelSize: 13
        font.bold: root.current
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        wrapMode: Text.NoWrap
    }

    MouseArea {
        id: ma
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.activated()
    }
}
