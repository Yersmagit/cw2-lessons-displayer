import QtQuick 2.15
import QtQuick 2.15 as QQ
import QtQuick.Shapes 1.15
import RinUI
import "."

// 文件管理页（自绘），严格对齐设计稿「文件管理页样式 light/dark.svg」：
// ┌ 面板 927×680、圆角 16（亮 #f2f2f2 / 暗 #292929）
// ├ 标题「文件管理」x=29 20px 加粗；右上角关闭按钮（RinUI dismiss 图标 size 20）
// ├ 左侧竖向选项卡 x=28 宽 180：每项 36 高、圆角 8、行距 5，图标 x=12（size 19，垂直居中）+ 文字 x=40（13px）；
// │   选中项有 15% 底色，左侧 3×16 圆角胶囊指示条（亮=黑 / 暗=白）与选项卡左边缘对齐
// └ 右侧内容卡片 x=228 / y=61（贴右、贴底，**左上 / 右下圆角 16、右上 / 左下直角**；
//     亮=白 98% + #e6e6e6 2px、暗=白 4% + 黑 4% 1px）
//     两个小节标题（15px 加粗）+ 4 列网格：格子 152 宽（缩略图**固定 128×80**、内缩 12、圆角 4 + 13px 标题）
//     当前页：格子 15% 底色 + 缩略图 2px 黑/白描边 + 标题加粗；历史页面标题 = 修改时间
//     滚动条用 RinUI 默认 ScrollBar，且**贴显示区最右**（右内边距改由内容列让出）
//
// 尺寸/资源：由 DataManagerOverlay 创建，而 Overlay 又只在打开时由 Loader 加载 →
// 关闭即销毁（缩略图 Image 用 cache:false，后端历史缩略图缓存由 closeDataManager 清空）。
Item {
    id: root
    objectName: "dataManagerPanel"

    signal closeRequested()
    signal pageActivated(int index)
    signal historyActivated(string file)

    // ---------- 配色（按设计稿；亮 = 白板模式、暗 = 黑板模式）----------
    readonly property bool lightMode: lessonsBackend.mode === "whiteboard"
    readonly property color fg: lightMode ? "#000000" : "#FFFFFF"    // 文字/图标/指示条/当前页描边
    readonly property color dimFg: lightMode ? "#99000000" : "#99FFFFFF"
    readonly property color panelColor: lightMode ? "#F2F2F2" : "#292929"
    readonly property color cardColor: lightMode ? "#FAFFFFFF" : "#0AFFFFFF"
    readonly property color cardBorderColor: lightMode ? "#E6E6E6" : "#0A000000"
    readonly property int cardBorderWidth: 1        // 卡片描边固定 1px（只要上边/左边/左上圆角）
    readonly property color pickColor: lightMode ? "#1A000000" : "#26F2F2F2"  // 选中项 / 当前页底色
    readonly property color hoverColor: lightMode ? "#0D000000" : "#1AFFFFFF"

    // ---------- 尺寸（设计稿 927.5×680.5 画布换算；**全部取整数**）----------
    readonly property int cardY: 61                // 内容卡片 y（= 标题栏高度）；cardX 见下方几何（居中）
    readonly property int cardRadius: 16
    readonly property int cardPadX: 32             // 卡片内左右内边距（4 列刚好 = 152 宽格子）
    readonly property int cardPadTop: 26           // 卡片内顶边到第一个小节标题
    readonly property int cardPadBottom: 24
    readonly property int blockGap: 10             // 内容列统一间距
    readonly property int sectionGap: 10           // 两段之间额外间距（10 + 10 + 10 = 30）
    readonly property int sectionTitleH: 20
    readonly property int tileGap: 9               // 格子横向间距
    readonly property int tileRowGap: 10           // 格子纵向间距
    readonly property int columns: 4
    readonly property int sidebarX: 28
    readonly property int sidebarY: 70
    readonly property int sidebarW: 180
    readonly property int tabItemH: 36
    readonly property int tabItemGap: 5
    readonly property int tabRadius: 8
    readonly property int tabIconX: 12             // 图标在选项卡内的 x
    readonly property int tabIconSize: 20
    // 「最近打开」用的 history 图标：墨迹比其它图标小 2px、且偏高 1px（上游字体问题）→ 单图标微调
    readonly property int tabIconSizeRecent: root.tabIconSize + 2
    readonly property int tabIconDyRecent: 0
    readonly property int tabIconDxRecent: -1
    readonly property int tabTextX: 41             // 文字在选项卡内的 x
    readonly property int tabPillW: 3
    readonly property int tabPillH: 16
    readonly property int tabPillRadius: 2         // ≥ 宽/2 → Qt 自动夹成胶囊形
    readonly property int tabSpringLeadMs: 250     // 指示条先行端时长（与图形菜单一致）
    readonly property int tabSpringTrailMs: 220    // 指示条跟随端时长（更短 → 跟随延迟更低）
    readonly property int tilePad: 12              // 缩略图在格子内的内缩（152-128=24 → 12）
    readonly property int tileRadius: 8
    readonly property int thumbRadius: 4
    readonly property int thumbLoadStepMs: 25   // 缩略图排队步长：名次 × 25ms = 启动延迟
    readonly property int thumbWDesign: 128        // 缩略图固定设计稿尺寸
    readonly property int thumbHDesign: 80
    readonly property int tileWDesign: root.thumbWDesign + root.tilePad * 2     // 格子 152
    readonly property real thumbAspect: 128 / 80   // 设计稿缩略图 128×80（仅比例）

    // 当前选项卡：0=最近打开 1=保存 2=另存至 3=导出图片（后三项暂未实装）
    property int tab: 0
    readonly property var tabLabels: ["最近打开", "保存", "另存至", "导出图片"]
    readonly property var tabIcons: ["ic_fluent_history_20_regular",
                                     "ic_fluent_save_20_regular",
                                     "ic_fluent_save_edit_20_regular",
                                     "ic_fluent_image_arrow_forward_20_regular"]

    // 已打开的页面（存页码 index）与历史页面（存 {file, title}）
    property var openPages: []
    property var historyPages: []
    // 每次打开面板 +1 → 并入缩略图 URL，强制重新请求（同一 URL 会命中 QML 缓存）
    property int openTick: 0

    // 面板尺寸：宽度**按内容定**（侧栏 + 左侧空白 + 刚包住 4 列的卡片），高度上限 660（视口随之减 60）
    width: Math.round(Math.max(360, Math.min((parent ? parent.width : 1000) * 0.86, root.fullPanelW)))
    height: Math.round(Math.max(280, Math.min((parent ? parent.height : 700) * 0.86, 660)))

    // ---------- 几何（全部整数）----------
    readonly property int sidebarEnd: root.sidebarX + root.sidebarW          // 侧栏右沿（208）
    readonly property int sideGutter: 20      // 侧栏↔卡片、卡片↔面板右沿的空白（设计稿 228-208）
    // 满尺寸卡片宽：4 列 152 格子 + 3 个间距 + 左右内边距 + 两侧描边
    readonly property int fullCardW: root.columns * root.tileWDesign
                                     + (root.columns - 1) * root.tileGap
                                     + root.cardPadX * 2 + root.cardBorderWidth * 2
    // 满尺寸面板宽 = 侧栏 + 20（左侧留白）+ 卡片（**右侧不留空，卡片贴住面板右沿**）
    readonly property int fullPanelW: root.sidebarEnd + root.sideGutter + root.fullCardW
    readonly property int roomW: root.width - root.sidebarEnd                // 侧栏右侧可用宽
    readonly property int cardH: root.height - root.cardY
    readonly property int cardX: root.sidebarEnd + root.sideGutter
    // 卡片宽 = 满尺寸，窄窗口时按可用宽退化（左侧留 20、右侧贴到面板右沿）
    readonly property int cardW: Math.max(240,
                                    Math.min(root.fullCardW, root.roomW - root.sideGutter))
    // 卡片内可用宽（扣掉左右内边距与两侧描边）→ 4 列平分，上限设计稿 152
    readonly property int availW: root.cardW - root.cardPadX * 2 - root.cardBorderWidth * 2
    readonly property int tileW: Math.max(60, Math.min(root.tileWDesign,
                                    Math.floor((root.availW - (columns - 1) * root.tileGap) / columns)))
    readonly property int thumbW: Math.max(40, root.tileW - root.tilePad * 2)
    readonly property int thumbH: Math.round(root.thumbW / root.thumbAspect)
    readonly property int contentW: root.columns * root.tileW + (root.columns - 1) * root.tileGap
    readonly property int scrollX: root.cardX + root.cardPadX + root.cardBorderWidth
    readonly property int scrollY: root.cardY + root.cardPadTop
    // 滚动区向**右**铺到卡片内右沿（只留左侧内边距）→ RinUI 滚动条贴页面最右；
    // 内容列宽仍是 4 列网格宽（右侧那 32px 内边距落在滚动区里、不再挤走滚动条）
    readonly property int scrollW: root.cardW - root.cardPadX - root.cardBorderWidth * 2
    readonly property int scrollH: root.cardH - root.cardPadTop - root.cardPadBottom

    function syncOpenPages() {
        var out = []
        var n = whiteboardBackend.pageCount
        for (var i = 0; i < n; i++) out.push(i)
        root.openPages = out
    }
    function syncHistoryPages() {
        var hp = whiteboardBackend.historyPages
        root.historyPages = (hp !== undefined && hp !== null) ? hp : []
    }

    // ---------- 缩略图加载时序：按「修改时间更晚 → 更早」排队 ----------
    // 两个分区排成一条优先级链（先已打开页面、再历史页面，段内各自按 mtime 倒序），
    // 名次 × thumbLoadStepMs 就是该格子的启动延迟 → 越新的缩略图越先开始加载。
    property var openLoadOrder: []
    property var histLoadOrder: []

    function rankOf(order, i) {
        var k = order.indexOf(i)
        return k < 0 ? 0 : k
    }
    function loadDelayFor(isHist, i) {
        var k = rankOf(isHist ? root.histLoadOrder : root.openLoadOrder, i)
                + (isHist ? root.openLoadOrder.length : 0)
        return k * root.thumbLoadStepMs
    }
    function rebuildLoadOrder() {
        var mt = whiteboardBackend.pageMtimes
        mt = (mt !== undefined && mt !== null) ? mt : []
        var n = whiteboardBackend.pageCount
        var o = []
        for (var i = 0; i < n; i++) o.push(i)
        o.sort(function (a, b) { return (Number(mt[b]) || 0) - (Number(mt[a]) || 0) })

        var hp = root.historyPages
        var h = []
        for (var j = 0; j < hp.length; j++) h.push(j)
        h.sort(function (a, b) {
            return (Number(hp[b].mtime) || 0) - (Number(hp[a].mtime) || 0)
        })

        root.openLoadOrder = o
        root.histLoadOrder = h
    }

    function refreshAll() {
        root.openTick++
        syncOpenPages()
        syncHistoryPages()
        rebuildLoadOrder()
    }
    Component.onCompleted: refreshAll()

    Connections {
        target: whiteboardBackend
        function onPageChanged() { root.syncOpenPages(); root.rebuildLoadOrder() }
        function onThumbsChanged() { root.openTick++ }
        function onHistoryChanged() { root.syncHistoryPages(); root.rebuildLoadOrder() }
    }

    // ---------- 面板底 ----------
    Rectangle {
        id: panelBg
        anchors.fill: parent
        radius: root.cardRadius
        color: root.panelColor
    }
    // 面板自身吞掉点击（否则会落到蒙层的"点外部关闭"上）；声明在内容之前 → 内容按钮仍在上层
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
    }

    // ---------- 标题栏 ----------
    QQ.Text {
        objectName: "dataManagerTitle"
        x: 29
        y: 24
        text: "文件管理"
        color: root.fg
        font.family: Qt.application.font.family
        font.pixelSize: 20
        font.bold: true
    }
    // 右上角关闭按钮（RinUI 图标）
    Item {
        id: closeBtn
        objectName: "dataManagerCloseBtn"
        width: 40
        height: 40
        x: root.width - 15 - width
        y: 12
        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: closeMa.containsMouse ? root.hoverColor : "transparent"
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        Icon {
            anchors.centerIn: parent
            name: "ic_fluent_dismiss_20_regular"
            size: 20
            color: root.fg
        }
        MouseArea {
            id: closeMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.closeRequested()
        }
    }

    // ---------- 左侧竖向选项卡 ----------
    // 每项 = 左图标 + 右文字；选中项有 15% 圆角底色，其左边缘有 3×16 圆角胶囊指示条。
    component DmTab: Item {
        id: tabItem
        objectName: "dataManagerTab_" + tabItem.label
        property string label: ""
        property string icon: ""
        property int index: 0
        property bool active: false
        property int iconSize: root.tabIconSize   // 默认尺寸；个别图标可单独微调
        property int iconDy: 0                    // 图标垂直微调（正值向下）
        property int iconDx: 0                    // 图标水平微调（负值向左）
        width: root.sidebarW
        height: root.tabItemH

        // 选中 / 悬停底色
        Rectangle {
            anchors.fill: parent
            radius: root.tabRadius
            color: tabItem.active ? root.pickColor
                                  : (tabMa.containsMouse ? root.hoverColor : "transparent")
            Behavior on color { ColorAnimation { duration: 120 } }
        }
        Icon {
            id: tabIcon
            x: root.tabIconX + tabItem.iconDx
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: tabItem.iconDy
            name: tabItem.icon
            size: tabItem.iconSize
            color: root.fg
        }
        QQ.Text {
            anchors.left: parent.left
            anchors.leftMargin: root.tabTextX
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: 1
            text: tabItem.label
            color: root.fg
            font.family: Qt.application.font.family
            font.pixelSize: 13
            elide: QQ.Text.ElideRight
        }
        MouseArea {
            id: tabMa
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: root.tab = tabItem.index
        }
    }

    Item {
        id: sidebar
        objectName: "dataManagerTabBar"
        x: root.sidebarX
        y: root.sidebarY
        width: root.sidebarW
        height: root.tabItemH * 4 + root.tabItemGap * 3
        // 首次创建时（字体度量还没稳定）不播指示条动画
        property bool animReady: false
        Component.onCompleted: animReady = true

        Column {
            id: tabColumn
            objectName: "dataManagerTabRow"
            width: parent.width
            spacing: root.tabItemGap
            DmTab { id: tabRecent; label: "最近打开"; icon: root.tabIcons[0]; index: 0
                    iconSize: root.tabIconSizeRecent
                    iconDy: root.tabIconDyRecent; iconDx: root.tabIconDxRecent
                    active: root.tab === 0 }
            DmTab { id: tabSave; label: "保存"; icon: root.tabIcons[1]; index: 1; active: root.tab === 1 }
            DmTab { id: tabSaveAs; label: "另存至"; icon: root.tabIcons[2]; index: 2; active: root.tab === 2 }
            DmTab { id: tabExportBtn; label: "导出图片"; icon: root.tabIcons[3]; index: 3; active: root.tab === 3 }
            // 四个选项卡的目标（按 index 取，供指示条定位）
            readonly property var tabs: [tabRecent, tabSave, tabSaveAs, tabExportBtn]
        }

        // 选中指示条：3×16 圆角胶囊，左侧与选项卡（轮廓）左边缘对齐、垂直居中。
        // **与图形菜单上方选项卡指示条同一款弹簧动画**（两端各自跑）：
        //  · 先行端：OutCubic（起步干脆、很快到位）
        //  · 跟随端：InOutQuad（起步慢被拽 → 中段快 → 稳稳落点）
        //   跟随端时长比先行端短 → **跟得紧一点、拖尾不会太久**（用户要求“跟随延迟低一点”）。
        // 向下切时**下端先冲出去、上端被拽着走** → 指示条先被拉长再收回 16；向上切则上端先行。
        // 注意：**不能用 Behavior + 按方向绑定 easing** —— 实测参数绑定只在首次求值，
        // 反向切换会沿用上一次的角色；所以用 4 个显式 NumberAnimation，由 applySpring() 按方向挑。
        Rectangle {
            id: tabIndicator
            objectName: "dataManagerTabIndicator"
            readonly property var target: tabColumn.tabs[Math.max(0, Math.min(root.tabLabels.length - 1,
                                                                              root.tab))]
            readonly property real targetTop: target
                ? (target.mapToItem(sidebar, 0, 0).y + (target.height - root.tabPillH) / 2) : 0
            readonly property real targetBottom: targetTop + root.tabPillH
            property real topEdge: 0
            property real bottomEdge: 0
            x: 0
            y: topEdge
            width: root.tabPillW
            height: Math.max(0, bottomEdge - topEdge)
            radius: root.tabPillRadius
            color: root.fg

            NumberAnimation {
                id: aTopLead
                target: tabIndicator; property: "topEdge"
                duration: root.tabSpringLeadMs; easing.type: Easing.OutCubic
            }
            NumberAnimation {
                id: aTopTrail
                target: tabIndicator; property: "topEdge"
                duration: root.tabSpringTrailMs; easing.type: Easing.InOutQuad
            }
            NumberAnimation {
                id: aBottomLead
                target: tabIndicator; property: "bottomEdge"
                duration: root.tabSpringLeadMs; easing.type: Easing.OutCubic
            }
            NumberAnimation {
                id: aBottomTrail
                target: tabIndicator; property: "bottomEdge"
                duration: root.tabSpringTrailMs; easing.type: Easing.InOutQuad
            }

            function stopSpring() {
                aTopLead.stop()
                aTopTrail.stop()
                aBottomLead.stop()
                aBottomTrail.stop()
            }
            // 直接落到目标（初始化 / 未勾 animReady 时用，不播动画）
            function snapToTarget() {
                stopSpring()
                topEdge = targetTop
                bottomEdge = targetBottom
            }
            // 弹簧过渡：向下（新选项卡序号更大）下端先行；向上则上端先行
            function applySpring(fromTab, toTab) {
                stopSpring()
                var t = tabColumn.tabs[Math.max(0, Math.min(root.tabLabels.length - 1, toTab))]
                if (!t)
                    return
                var tl = t.mapToItem(sidebar, 0, 0).y + (t.height - root.tabPillH) / 2
                var tb = tl + root.tabPillH
                var t0 = topEdge
                var b0 = bottomEdge
                if (toTab > fromTab) {          // 向下：下端先冲出去，上端被拽过去
                    aBottomLead.from = b0; aBottomLead.to = tb; aBottomLead.start()
                    aTopTrail.from = t0; aTopTrail.to = tl; aTopTrail.start()
                } else if (toTab < fromTab) {   // 向上：上端先冲出去，下端被拽过去
                    aTopLead.from = t0; aTopLead.to = tl; aTopLead.start()
                    aBottomTrail.from = b0; aBottomTrail.to = tb; aBottomTrail.start()
                } else {
                    snapToTarget()
                }
            }

            Component.onCompleted: snapToTarget()
            // 目标选项卡变了 → 按"从上一个选项卡到新选项卡"的方向播弹簧
            property int lastTab: 0
            onTargetChanged: {
                if (sidebar.animReady)
                    applySpring(lastTab, root.tab)
                else
                    snapToTarget()
                lastTab = root.tab
            }
        }
    }

    // ---------- 右侧内容卡片 ----------
    // 按设计稿的卡片路径：**只有左上 / 右下是圆角**，右上 / 左下为直角。
    // Rectangle 不支持逐角圆角 → 用 Shape 描出路径（RinUI 自身也依赖 QtQuick.Shapes）。
    // 描边只有 **1px**，且**只画上边 + 左边 + 左上圆角**：右侧/下侧与面板边缘重合，不需要描边。
    Shape {
        id: card
        objectName: "dataManagerCard"
        x: root.cardX
        y: root.cardY
        width: root.cardW
        height: root.cardH
        antialiasing: true

        readonly property int rad: root.cardRadius

        // 卡片底（填充）：左上 / 右下圆角，右上 / 左下直角
        ShapePath {
            fillColor: root.cardColor
            strokeColor: "transparent"
            strokeWidth: 0

            startX: card.rad
            startY: 0
            PathLine { x: card.width; y: 0 }                              // 右上：直角
            PathLine { x: card.width; y: card.height - card.rad }
            PathArc {
                x: card.width - card.rad
                y: card.height
                radiusX: card.rad
                radiusY: card.rad
                direction: PathArc.Clockwise                           // 右下：圆角
            }
            PathLine { x: 0; y: card.height }                              // 左下：直角
            PathLine { x: 0; y: card.rad }
            PathArc {
                x: card.rad
                y: 0
                radiusX: card.rad
                radiusY: card.rad
                direction: PathArc.Clockwise                           // 左上：圆角
            }
        }

        // 描边（开放路径）：上边 → 左上圆角 → 左边，路径内缩 0.5px 让 1px 线完整落在卡片内
        ShapePath {
            fillColor: "transparent"
            strokeColor: root.cardBorderColor
            strokeWidth: root.cardBorderWidth
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: card.width
            startY: 0.5
            PathLine { x: card.rad; y: 0.5 }
            PathArc {
                x: 0.5
                y: card.rad
                radiusX: card.rad - 0.5
                radiusY: card.rad - 0.5
                direction: PathArc.Counterclockwise                    // 左上圆角
            }
            PathLine { x: 0.5; y: card.height }
        }
    }

    // ---------- 分区标题 ----------
    component SectionTitle: QQ.Text {
        width: parent ? parent.width : 0
        height: root.sectionTitleH
        color: root.fg
        font.family: Qt.application.font.family
        font.pixelSize: 15
        font.bold: true
        verticalAlignment: QQ.Text.AlignVCenter
    }

    // ---------- 「最近打开」内容（滚动条用 RinUI 默认 ScrollBar）----------
    Flickable {
        id: flick
        objectName: "dataManagerScroll"
        visible: root.tab === 0
        x: root.scrollX
        y: root.scrollY
        width: root.scrollW
        height: root.scrollH
        contentWidth: width
        contentHeight: contentCol.height
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        Column {
            id: contentCol
            width: root.contentW
            spacing: root.blockGap

            SectionTitle {
                objectName: "dataManagerOpenTitle"
                text: "已打开的页面"
            }
            Grid {
                id: openGrid
                objectName: "dataManagerOpenGrid"
                columns: root.columns
                columnSpacing: root.tileGap
                rowSpacing: root.tileRowGap
                Repeater {
                    model: root.openPages
                    delegate: PageTile {
                        required property var modelData
                        required property int index
                        width: root.tileW
                        thumbW: root.thumbW
                        thumbH: root.thumbH
                        pad: root.tilePad
                        // 按「修改时间更晚 → 更早」排队加载
                        loadDelay: root.loadDelayFor(false, index)
                        title: String(modelData + 1)
                        current: modelData === whiteboardBackend.currentPage
                        source: "image://whiteboard/thumb?page=" + modelData
                                + "&v=" + whiteboardBackend.thumbVersion
                                + "&o=" + root.openTick
                        onActivated: root.pageActivated(modelData)
                    }
                }
            }

            Item { width: 1; height: root.sectionGap }   // 分区之间的间隔（10 + 19 + 10 = 39，对齐设计稿）

            SectionTitle {
                objectName: "dataManagerHistoryTitle"
                text: "历史页面"
            }
            QQ.Text {
                objectName: "dataManagerHistoryEmpty"
                visible: root.historyPages.length === 0
                width: parent.width
                height: root.sectionTitleH
                text: "暂无历史页面"
                color: root.dimFg
                font.family: Qt.application.font.family
                font.pixelSize: 13
                horizontalAlignment: QQ.Text.AlignHCenter
                verticalAlignment: QQ.Text.AlignVCenter
            }
            Grid {
                id: histGrid
                objectName: "dataManagerHistoryGrid"
                columns: root.columns
                columnSpacing: root.tileGap
                rowSpacing: root.tileRowGap
                Repeater {
                    model: root.historyPages
                    delegate: PageTile {
                        required property var modelData
                        required property int index
                        width: root.tileW
                        thumbW: root.thumbW
                        thumbH: root.thumbH
                        pad: root.tilePad
                        // 按「修改时间更晚 → 更早」排队加载（接在已打开页面之后）
                        loadDelay: root.loadDelayFor(true, index)
                        title: String(modelData.title || "")
                        source: "image://whiteboard/hist?file=" + modelData.file
                                + "&v=" + Math.round(Number(modelData.mtime) || 0)
                                + "&o=" + root.openTick
                        onActivated: root.historyActivated(String(modelData.file || ""))
                    }
                }
            }
            Item { width: 1; height: root.blockGap }
        }
    }

    // ---------- 其他选项卡（保存 / 另存至 / 导出图片）暂未实装：空页占位 ----------
    QQ.Text {
        objectName: "dataManagerPlaceholder"
        visible: root.tab !== 0
        x: root.scrollX
        y: root.scrollY
        width: root.scrollW
        height: root.scrollH
        text: "暂未实装"
        color: root.dimFg
        font.family: Qt.application.font.family
        font.pixelSize: 13
        horizontalAlignment: QQ.Text.AlignHCenter
        verticalAlignment: QQ.Text.AlignVCenter
    }
}
