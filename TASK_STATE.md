# Task State

> **本文件是 Agent 工作流的一部分，不是可选的草稿**：
> 任务开始（定契约前）由主 Agent 填「基本信息 / 接口契约 / 文件所有权 / 验收命令」；
> 实现与自测后填「测试结果 / 截图路径」；Reviewer 回填「Reviewer 结论」；
> 收尾时写「变更记录 / 未决问题」。**每轮任务结束必须更新，不要留空占位。**
>
> 字段说明与仓库约定见 `AGENTS.md`；前端 token 见 `.github/agents/memory/design-system.md`。

## 基本信息
- 任务类型: `feature`（坐标系/视框映射重构）
- 风险等级: **high**（`main.py` 的存储 meta schema + 全部 QML 坐标出入口 + 烘焙管线）
- 目标: 把"画布坐标 = 当时屏幕逻辑像素"的硬耦合，改成"画布坐标 + 视框（viewBox）"模型：
  ① meta 记**视框**（宽高 = 创建时屏幕逻辑尺寸，原点 0,0），**不再记 `device_pixel_ratio`**；
  ② 缩放由"屏幕实际宽高 / 视框宽高"现算；
  ③ 屏幕分辨率变了：宽高比变了就补足短边 + 原点前移一半（内容居中、不截断），没变就只改缩放；
  ④ 旧数据（只有 `screen_*` + `device_pixel_ratio`）无换算直接兼容并补写视框键。


**风险等级判定（本仓库口径）**
- `low`：纯文案、单个 QML 常量微调、`_dev/` 测试脚本改动。
- `medium`：单个 QML 组件布局/配色/动画；不触碰 `_tf_*` / `_ax_*` / `_pf_*` 的后端小改。
- `high`：`main.py` 里的图形/坐标系/多页/存储路径；`main.py` 与 QML 的接口（`@Property`/`@Slot`）；
  文件管理页这类会读写用户数据的模块。

## 接口契约
- **新增 meta 键**：`frame_x` / `frame_y` / `frame_w` / `frame_h`（**内容框**，创建后不变）+ `view_x/y/w/h`
  （当前视口快照，仅供记录，不参与计算）。**不再写 `device_pixel_ratio`**；`screen_width/height` 保留（诊断）。
- **新增 `@Property`**（notify=`viewChanged`）：`viewScale`、`viewOriginX`、`viewOriginY`、
  `viewFrameWidth/Height`（当前视口）、`viewContentWidth/Height`（内容框）。
- **坐标约定（对 QML）**：所有 `@Slot` 入参与 `@Property` 返回的几何量一律是**屏幕视口坐标**
  （= QML 鼠标坐标 / 窗口逻辑像素）；**画布坐标只在后端内部与 SQLite 里出现**。
- **新增 `StrokeStore` 方法**：`get_frame()` / `legacy_frame()` / `set_frame()` / `set_view()`。
- `new_session(..., frame=None)`：新页/清屏新库**继承内容框**（所有页共用一个坐标系）。

## 文件所有权
| 文件/目录 | 主责Agent | 状态 |
|---|---|---|
| `main.py`（`StrokeStore` meta schema + `WhiteboardBackend` 视框映射 + 19 处槽/属性出入口） | Orchestrator | 完成 |
| `_dev/_verify_bugfix.py`（新增 [8] 视框映射 20 条断言） | Orchestrator | 完成 |
| `AGENTS.md`（§5 补坐标系/视框硬约束） | Orchestrator | 完成 |
| `.github/agents/memory/*` | Orchestrator | 完成 |
| `docs/CHANGELOG-unreleased.md` | Orchestrator | 完成 |
| `TASK_STATE.md` | Orchestrator | 完成（本轮账本） |


> 约定：同一文件同一时间只能有一个写者；Reviewer/Explorer 永远只读。

## 验收命令
- 语法：`python -m py_compile main.py`
- 回归（六套，缺一不可）：
  `_dev/_verify_shapes.py`、`_dev/_verify_shapes_qml.py`、`_dev/_verify_bugfix.py`、
  `_dev/_verify_fix3.py`、`_dev/_verify_memory.py`、`_dev/_verify_solid.py`
- 像素一致性（前端必跑）：`_dev/_render_menu.py`（要求「差异采样点: 0」+ 墨量比 ≈1.000）
- 前端截图：`DM_SHOT=1` + `_dev/_verify_shapes_qml.py` → `_dev/_dev_out/datamanager*.png`
- 同步安装副本：`Copy-Item` 到 `plugins\com.yersmagit.lessonsdisplayer\`（`ShapeMenu.qml` 需字节级保留 `chipRow.spacing: 0`）+ 逐文件 MD5 校验
- **不要**执行 `git commit` / `git push` / `git tag`（由仓库作者完成）

## 探索结论
- 是否已完成: yes（主 Agent 直接通读 `main.py` 存储层 + 全部坐标出入口）
- 摘要:
  - 现状：笔迹点 = **当时屏幕的逻辑像素**；`meta` 写 `screen_w/h` + `device_pixel_ratio`，但 DPR **从未被读回**
    （`grep` 仅写入处）→ 分辨率/DPR 一变，旧笔迹直接错位（本次修复的根因）。
  - 坐标出入口共 **14 个 `@Slot` + 8 个 `@Property`**（清单见变更记录），内部互调 4 处
    （`beginLine → beginFocusProbe` ×2、`moveLine → dragFocusProbe` ×2、`rotatedScaleTo → applyTransform`）→ 
    拆成「入口转一次 + 内部实现吃画布坐标」防双重转换。
  - 烘焙管线：`_image` 尺寸 = `_canvas_size`（= 屏幕逻辑尺寸）；全部 `QPainter(self._image/_plain)` 10 处注入
    `_apply_view()`（translate + scale）；图层预烘焙 `_stroke_layer` 仍在**画布 1:1** 坐标里（不能改，否则失去整数 blit 优化）。
  - **关键设计修正**：若按"每次在上次视框上再加 Δ"会**累积**（来回切分辨率后内容越缩越小），
    故改为“从不可变内容框 `frame_*` 每次现算” —— 单次变化结果与用户公式完全一致（已断言：
    更宽屏 → `2240x960, 原点 -352, 缩放 0.9375`），但幂等且可回退（切回原分辨率 → 视口 = 内容框、缩放 1）。
- 关键文件/行号: `main.py` `StrokeStore.get_frame/legacy_frame/set_frame/set_view`、
  `WhiteboardBackend._load_frame/_fit_view/_apply_view/_v2c/_c2v/_c2v_pairs/_c2v_flat/_v2c_poly`、
  `set_canvas_size`(触发 `_fit_view`)、`_ensure_image/_redraw_active/_render_all/_render_selection_overlay/`
  `_build_preview_base/_render_modify_preview/_render_thumb/moveStroke(橡皮)/台体回填/旋转预览`
- 基线: HEAD `f7ffc6d`（2026-10-28）

## 测试结果
- 命令: `python -m py_compile main.py` + 六套 `_dev/_verify_*.py` + `_dev/_render_menu.py`
- 结果: compile=0；六套全部「FAILED: 无 —— 全部通过」；render 无任何「差异采样点: N>0」/墨量比 ≥1.1，
  既有基线不变（`circle 1.049` / `hyp 1.011`）
- 新增断言：`_dev/_verify_bugfix.py` [8] 共 **23 条**（全部 PASS）: meta 写 `frame_*` 且**无** `device_pixel_ratio`；
  同分辨率 = 恒等映射；更宽屏 → 视口高不变/宽 = 高×新宽高比/原点 x = -(Δ/2)/缩放 = 屏宽÷视口宽/
  画布中心→屏幕中心/四角不出界；幂等；视口↔画布互逆（误差 <1e-9）；
  端到端（视口坐标输入 → 落盘点为画布坐标、烘焙图尺寸 = 视口、中心有墨）；
  更窄屏 → 视口宽不变/高补足/原点 y = -(Δ/2)/仍垂直居中；
  **换回原分辨率不累积**；老库（只有 `screen_*`+DPR）迁移成视框且几何不变；
  落盘顶点 ≤ 2 位小数（含 130 点圆轮廓）；UI 尺寸恒定 3 条（锚点屏幕 28px / 画布 28÷缩放 / 端点命中 15px 中 17px 不中）。
- 时间: 2026-10-31


## 截图路径（前端）
- 本轮无 QML 改动 → 未截图（Image 仍 `anchors.fill: parent`，因为烘焙图已按视口尺寸产出）
- 面板/弹层: 沿用上一轮 `_dev/_dev_out/datamanager*.png`

## Reviewer 结论
- 状态: **待审**（本轮由 Orchestrator 自测完毕，尚未派发 Reviewer）
- 轮次: 0
- 阻断项: 待填
- 放行条件: 待填。自测已确认：六套回归全 PASS、render 无差异、新增 20 条断言全 PASS

## 未决问题
- 本轮新增：**历史库未回溯压缩**——取 2 位小数只对**新写入**生效；现有库里仍有大量超精度小数
  （实测 `canvas_1789188905382.db` 1,476 个、`canvas_1789197608230.db` 67,976 个坐标超 2 位）。
  如需瘦身要额外做一次性迁移（重写 `points`），这属改写用户数据，**未获授权前不做**。
- 本轮新增：`figureAngleAnchor` 的「角平分线 28px」与 `hitLineEndpoint` 的「16px 命中半径」仍是**画布单位**
  （缩放 ≠1 时屏幕上会等比放大/缩小）→ 若要求 UI 尺寸恒定，需改成除以 `viewScale`。
- 本轮新增：缩略图/烘焙图分辨率 = 视口的**画布**分辨率（缩放 >1 时放大略软）；后续若要求极清晰，
  可把 `_apply_view` 的 scale 提到屏幕 DPR。
- ✅ 已解决（2026-10-31）：`figureAngleAnchor` 的 28px 与 `hitLineEndpoint` 的 16px 已改为**屏幕像素恒定**
  （画布单位 = `28 / viewScale`、`16 / viewScale`）。新增 3 条断言锁死（`_verify_bugfix.py` [8]）。
- 文件管理页「保存 / 另存至 / 导出图片」三个选项卡仍是占位，功能未实装。
- 安装副本 `qml/specialmode/ShapeMenu.qml` 仍有用户手改的 `spacing: 3 → 0`（`chipRow`），**这是唯一允许的单向例外**，
  本轮未动；下次同步必须字节级保留，别覆盖。
- `v1.1.0-alpha` 之后的改动已提交（`f7ffc6d`）但未打 tag；下一版号（`1.1.1` 还是 `1.2.0`）待作者决定。

## 变更记录
- 2026-10-31 · **文档/源码一致性核查 + 安装副本回灌**：
  ① 源码与安装副本的 3 处 QML 差异里，两处属用户对副本的手改（`EraserMenu.qml`：`height 120→104`、
  `spacing 10→4`；`DataManagerPanel.qml`：`cardPadBottom 24→0`）→ 按仓库惯例**回灌到源码**，
  另一处 `ShapeMenu.qml`（`chipRow.spacing 3→0`）保留为文档化例外。回灌后**除该例外，全库源码与副本一致**。
  ② 修正文档过期事实：`AGENTS.md §1` 的基线/`git status` 清单（原来写“工作区应保持干净”已不成立）、
  `docs/CHANGELOG-unreleased.md` 的 `main.py` 行数（12001 → **12395**）与状态行（补“f7ffc6d 之后又有未提交改动”）、
  `TASK_STATE.md` 断言数（20 → **23**）、`.github/agents/memory/design-system.md`（卡片上内边距 30→**26**、
  面板宽 ≈931→**929**）、`index.md` 新增第 14 条坐标系硬约束并重排编号。
  ③ 恢复源码缺失的 `__init__.py`（`from .main import Plugin`，仅存在于安装副本、未入库）——插件包导入必需。
  验证：六套回归全 PASS、render 无差异；回灌后源码与副本的 `main.py`/`qml/**`/`__init__.py` MD5 逐个比对仅
  `ShapeMenu.qml` 不同。**未提交 git**。
- 2026-10-31 · **UI 尺寸与缩放解耦**（关掉一条未决问题）：角度提示胶囊锚点与端点手柄命中半径
  原来直接以**画布单位**写死（`_PF_HINT_R = 28` / `16.0*16.0`），视框缩放 ≠1 时在屏幕上会等比放大/缩小。
  现改为**屏幕像素恒定**：`_pf_bisect_pt(prev, start, end, dist)` 新增 `dist` 参数，调用处传
  `_PF_HINT_R / viewScale`；`hitLineEndpoint` 用 `r = 16.0 / viewScale`（与 QML `EndHandle.hitR = 16` 对齐）。
  新增断言（`_verify_bugfix.py` [8] 共 3 条，均在缩放 = 0.9375 的非恒等映射下）：
  ① 锚点在屏幕上距角顶点 28.00px（画布 29.87）；② 锚点画布距离 = 28/缩放（误差 <0.6）；
  ③ 端点命中：屏幕偏移 15px 命中、17px 不命中。
  六套回归 + render 全 PASS（`_verify_shapes` 里原有的「锚点距顶点恒 28px」断言在缩放=1 下仍成立）。
  `main.py`（MD5 `8F1AA34615F9FDEA1366F7EEE6057A16`）已同步安装副本。
  **未提交 git**。
- 2026-10-31 · **顶点坐标落盘取 2 位小数**（承接上一轮的坐标精度讨论）。新增模块级 `_q2()` /`_q_pts()`
  （`_pat_json` 一并取整），在 `StrokeStore.add_stroke` / `insert_stroke` / `update_stroke` 三条写入路径
  统一把 **x,y 取 2 位小数**（pressure 等高精度分量不动）→ 圆/椭圆/抛物线等**曲线采样顶点**也一并收敛。
  实测真实库可省 **35%~37%** 的 `points` 文本（`canvas_1789197608230.db`：1,346 笔 2,046,009 → 1,289,773 字符）。
  **设计取舍（重要）**：取整**只在落盘层**，内存几何保持原精度——`_verify_shapes` / `_verify_solid` 里有
  抛物线「偏差 < 1e-9」等几何不变量断言，内存也取整会直接把它们打挂（第一版就试过并已回退）。
  代价：重启/切页/导入读回的点列与内存相差 ≤ 0.005 px（亚像素，不可见）。
  因此两处旧断言从「精确相等」改为「按落盘精度比较」（`_verify_shapes` 多边形读回用 `M._q2` 预期值；
  `_verify_memory` 两处 `same(..., 0.005)`）。新增断言：`_verify_bugfix.py` 先画一条直线 + 一个圆
  （130 个三角采样顶点），再直读 SQLite 校验**每个 x,y 都 ≤ 2 位小数**。
  六套回归 + render 全 PASS（`_verify_shapes_qml` 首轮因连跑时 CPU 争用报 3 条动画时序断言，
  单独重跑两次均全绿，属已知测试抖动而非回归）。`main.py`（MD5 `C3A1FED5EA77EE2FF5EB0409CD8C9E8D`）已同步安装副本。
  **未提交 git**。
- 2026-10-31 · **坐标系重构：引入视框（viewBox）映射**。`meta` 改为记「内容框」`frame_x/y/w/h`
  （= 创建时屏幕逻辑尺寸，原点 0,0，**永不修改**）+ 视口快照 `view_x/y/w/h`；**不再写 `device_pixel_ratio`**，
  缩放 = 屏幕宽 ÷ 视口宽现算。分辨率变化：新屏更宽 → 高不变、宽补足 `Δx=(x2/y2*y1-x1)/2`、原点 x −= Δx；
  更高 → 宽不变、高补足、原点 y −= Δy；宽高比不变 → 只改缩放。**实现上改为每次从内容框现算**
  （不是在上次视口上累加），因此幂等、可回退，来回换分辨率不会把内容越缩越小。
  旧库（只有 `screen_*`+DPR）按 `frame=(0,0,screen_w,screen_h)` 迁移，点列无需换算（旧点本来就是逻辑像素）。
  后端新增 `StrokeStore.get_frame/legacy_frame/set_frame/set_view`、`WhiteboardBackend._load_frame/_fit_view/
  _apply_view/_v2c/_c2v/_v2c_poly/_c2v_pairs/_c2v_flat` 与 `viewScale/viewOriginX/Y/viewFrameWidth/Height/
  viewContentWidth/Height`（notify `viewChanged`）；14 个入参槽（`beginStroke/moveStroke/beginLine/moveLine/
  beginFocusProbe/dragFocusProbe/beginSelection/updateSelection/clickSelect/applyTransform/snapScaleAspect/
  rotatedScaleTo/dragLineHandle/hitLineEndpoint`）与 8 个几何属性（`focusProbeHandles/focusProbePoint/
  figureSnapGuide/figureAngleAnchor/figureSnapHighlight/scaleAspectGuide/selectionLineHandles/selectionRect`）
  在边界处统一换算；内部互调（`beginLine→_begin_focus_probe`、`moveLine→_drag_focus_probe`、
  `rotatedScaleTo→_apply_transform`）走画布实现避免双重转换。烘焙管线 10 处 `QPainter` 注入 `_apply_view`。
  **QML 零改动**（烘焙图仍按视口尺寸产出，`Image` 仍 `anchors.fill`）。
  验证：六套回归全 PASS；`_verify_bugfix.py` 新增 [8] 20 条断言全 PASS；`_render_menu.py` 无差异
  （`circle 1.049` / `hyp 1.011` 基线不变）。`main.py`（MD5 `23945950F74FBA14AEE779CF9F361165`）已同步安装副本，两侧一致。
  **未提交 git**（由作者完成）。
- 2026-10-29 · **缩略图刷新一致性**：`addPage()` 补 `_bump_thumbs()`（与 `openHistoryPage()` / 切页 一致；
  `deletePage` 仍不 bump，由 `pageRemoved → reloadTick++` 兜底）。断言：`_dev/_verify_memory.py` **9 条**
  （加页版本递增 + `thumbsChanged` 发射 1 次 + [M3c] 7 条：基准墨迹 / 版本递增 / 缓存失效 / 墨量增长 /
  导入后版本递增 / 导入后缓存清空 / 导入内容一致）；`_dev/_verify_shapes_qml.py` **6 条**
  （`:2460` URL 通道、`:2464` `&v=7&`+`&o=`、`:2468` `cache=false`、`:2478` 历史 URL 通道、`:2485` `&v=<mtime>`、
  `:2500` `thumbsChanged.emit()` → 7 个 URL 的 `&o=` 全变）。
  同时**纠正上轮误报**：`DataManagerPanel.qml:533-535` / `:577-579` 的缩略图 URL 一直带 `&v=`/`&o=`
  （跨行拼接，单行 grep 误判）；已改 `memory/index.md` 第 12 条与 `AGENTS.md §2`（`libs/` 实为**已跟踪**，非 gitignored）。
  六套回归 + render 全 PASS；`main.py`（MD5 `925DD8B162E1082745FEFE6E0E2AE69D`）与
  `qml/specialmode/PageListMenu.qml`（MD5 `4010F2816C5A06D45818F646ADD95EF8`）已同步安装副本，两侧一致。
  未提交 git（由作者完成）；`libs/perfect_freehand/` 早已在 `f7ffc6d` 入库，无需再提交。
- 2026-10-28 · Agent 工作流验收 + 文档漂移修正：`AGENTS.md §1`（基线改为「tag v1.1.0-alpha + 后续已提交 f7ffc6d，工作区应干净」）、
  `AGENTS.md §5`（`_tf_*`/`_ax_*` 是状态字段而非方法前缀，改为点名真实入口 + 行号收窄到 3744-3748 / 3768-3771）、
  `AGENTS.md §2/§3`（`docs/` 标注 gitignored；补 UTF-8 控制台前置步骤；补墨量比已知基线 `circle 1.049` / `hyp 1.011`）、
  `.github/agents/memory/index.md` 补 3 条后端硬约束（命名 / `v=` 只用于破缓存 + 两处现存违例 / `pages.json` 非原子写与删页不可撤销）、
  `docs/CHANGELOG-unreleased.md` 状态行改「已提交未发版」+ 给「建议的提交拆分」加过期说明 + 追加文档修正留痕。
  **未改任何代码**；compile=0，六套回归 + render 全 PASS（结果见上）；Reviewer 第 1 次派发因模型侧 502 失败、重派后放行，
  5 条建议项已全部采纳。未同步安装副本（无 `main.py`/`qml` 变更）。
- 2026-10-28 · 工作流文档落地（`AGENTS.md` 补全目录/命令/QML 与后端约定/同步副本/收尾清单；
  `TASK_STATE.md` 补仓库口径的风险分级与验收命令；`releaser.agent.md` 按新版规范重写；
  `orchestrator.agent.md` 修正工具名并加"收尾三件套/不提交 git"；新增 `.github/agents/memory/{index,design-system}.md`
  与 `docs/CHANGELOG-unreleased.md`）· 未改代码，六套回归 + render 全 PASS。
- 2026-10-28 · `docs/CHANGELOG-unreleased.md` 扩写：补上更早期改动（换课按钮、悬停渐隐、迷你模式适配、
  平板适配、主程序设置页入口、新增设置项、预备时段高亮修复），并按"不写像素/参数微调、不单列新功能的后续修补"
  的口径重排；基线核对到 `v1.1.0-alpha`（`main.py` 3021 → 12001 行）。

