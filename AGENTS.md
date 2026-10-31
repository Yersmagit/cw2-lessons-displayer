# AGENTS.md

> 本仓库（`cw2-lessons-displayer`：Class Widgets 2 插件「LessonBoard 课程灵动条 & 手写板」）里
> AI Agent 的**唯一入口文档**。任务开始先读；仓库事实有变化时**必须**同步更新本文件。
>
> 相关文件：任务账本 `TASK_STATE.md`、长期记忆 `.github/agents/memory/index.md`、
> 未发布改动日志 `docs/CHANGELOG-unreleased.md`、主 Agent `.github/agents/orchestrator.agent.md`。

## 1. 这是什么项目

- 形态：Class Widgets 2 的插件（`cwplugin.json` 里的 `id = com.yersmagit.lessonsdisplayer`）。
- 组成：**后端一个文件** `main.py`（PySide6 + QML 桥接、手写笔迹存储与烘焙）+ **前端** `qml/`。
- 能力：课程表灵动条（`LessonsDisplay.qml`）、全屏手写板（特殊模式：白板/黑板、笔/橡皮/选择/直线/形状/坐标系、多页、文件管理）。
- 版本：`cwplugin.json.version` 与 `pyproject.toml [project].version` **两处必须一致**。
- 当前基线：tag `v1.1.0-alpha`（提交 `93a6620`）；其后的大批改动**已提交**为 `f7ffc6d`（2026-10-28，尚未打 tag）。
  在 `f7ffc6d` 之上又有一批**尚未提交**的工作区改动（坐标系视框映射 / 坐标 2 位小数落盘 / UI 尺寸与缩放解耦 /
  文件管理页布局等）——`git status` 应为：已改 `main.py`、`AGENTS.md`、`TASK_STATE.md`、
  `qml/specialmode/{EraserMenu,PageListMenu}.qml`、`qml/specialmode/datamanager/DataManagerPanel.qml`、
  `.github/agents/memory/{index,design-system}.md`，另有**未跟踪**的 `__init__.py`（`from .main import Plugin`，
  插件包必需，未入库）；改动由仓库作者自行提交，Agent 不执行 commit/push/tag。
  `docs/CHANGELOG-unreleased.md` 是「`v1.1.0-alpha` → 现在」全部未发布改动的可读摘要。

## 2. 目录职责

| 路径 | 职责 | 备注 |
|---|---|---|
| `main.py` | 后端全部逻辑（`WhiteboardBackend` / `LessonsBackend` / `StrokeStore` / `WhiteboardImageProvider`） | 单文件巨型文件，改前先 grep 定位 |
| `qml/LessonsDisplay.qml` | 灵动条主界面 | 用 `lessonsBackend.scaleFactor` 缩放 |
| `qml/SpecialModeWindow.qml` | 手写板窗口/画布/弹层调度 | 手写板所有弹层都挂这里 |
| `qml/specialmode/` | 手写板部件（工具栏、各类菜单、选中态、提示、预览） | 尺寸固定 px，不乘 scaleFactor |
| `qml/specialmode/datamanager/` | 文件管理页（`DataManagerOverlay` → `DataManagerPanel` → `PageTile`） | Loader 按需加载，关闭即销毁 |
| `qml/settings/` | 设置页 | — |
| `previews/`、`icon.png` | 预览图与插件图标 | — |
| `_research_extract/` | 反编译参考（主程序内部实现） | **只读参考，不要打包/引用** |
| `_dev/` | 本机开发工具：六套 offscreen 测试、像素渲染比对、桩模块 | **gitignored，不进安装副本** |
| `libs/perfect_freehand/` | vendored 依赖（手写笔迹仿真）：`main.py` 里 `sys.path.insert(..., "libs")` + `from perfect_freehand import get_stroke`，失败回退 `_HAS_PERFECT_FREEHAND=False` | **已入库跟踪**（`f7ffc6d` 加入），许可见同目录 `PERFECT_FREEHAND_LICENSE.txt` |
| `RinUI/`、`.venv*/`、`__pycache__/`、`log/` | 依赖/运行产物 | gitignored |
| `.github/agents/` | Agent 说明与长期记忆 | 见 §8 |
| `docs/` | 未发布改动日志 | **gitignored**（本地留痕，不入库；`.gitignore` 显式忽略 `docs/CHANGELOG-unreleased.md`） |

## 3. 环境与命令

- **运行/测试用主程序 venv**：`C:\Users\32852\Desktop\文件\Class-Widgets-2\.venv\Scripts\python.exe`
  （仓库里的 `.venv-1` / `.venv-2` 只用于局部试验，别当默认解释器）。
- **安装副本**（在真实主程序里验证用）：`C:\Users\32852\Desktop\文件\Class-Widgets-2\plugins\com.yersmagit.lessonsdisplayer\`。
- 语法检查：`python -m py_compile main.py`
- **先切 UTF-8 控制台**（Python 输出 UTF-8，而控制台默认 936 → 中文 PASS/FAILED 行会乱码，
  看起来像测试挂了）：

  ```powershell
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $env:PYTHONIOENCODING = 'utf-8'
  ```

- **六套离屏回归**（全部在 offscreen 下跑，缺一不可）：

  ```powershell
  $py = 'C:\Users\32852\Desktop\文件\Class-Widgets-2\.venv\Scripts\python.exe'
  foreach ($s in '_verify_shapes','_verify_shapes_qml','_verify_bugfix','_verify_fix3','_verify_memory','_verify_solid') {
      & $py -u "_dev\$s.py" *> "_dev\_dev_out\$s.log"
      (Get-Content "_dev\_dev_out\$s.log" -Encoding Unicode | Select-String 'FAILED:' | Select-Object -Last 1).Line
  }
  ```

- **像素一致性**（形状/立体/坐标系小图标 QML↔Python）：`& $py -u _dev\_render_menu.py`
  → 关注「差异采样点: 0」与墨量比 ≈1.000。已知基线例外：`circle ≈1.049`、`hyp ≈1.011`
  （`shapes` 那批的曲线近似），其余 1.000~1.005；出现新的大偏差（如 1.11）才是"少画/多画"。
- **截图**：设环境变量 `DM_SHOT=1` 跑 `_dev\_verify_shapes_qml.py`，会输出
  `_dev\_dev_out\datamanager.png` / `datamanager_panel.png`（2× 的 `datamanager_zoom.png`）。
- 没有本地构建命令：`.cwplugin` / `.zip` 由 CI（`.github/workflows/release.yml`）在打 tag 时生成。

## 4. 前端约定（QML）

1. **尺寸一律用整数**（坐标/宽高/字号/圆角）；派生几何用 `Math.round` / `Math.floor` 并声明成 `int`。
   圆角需要 `w/2` 时写整数（如 3 宽胶囊写 `radius: 2`，Qt 会自动夹成胶囊）。
2. **图标只用 RinUI `Icon`**：
   - 名字必须能在 `.venv\Lib\site-packages\RinUI\assets\fonts\FluentSystemIcons-Index.js` 里搜到，**只认 `*_20_regular` / `*_20_filled`**；
   - `size ≈ 设计稿 Segoe 字号 × 1.25`（详见 `.github/agents/memory/design-system.md`）；
   - 不要给 `Icon` 设 `width/height`，不要改 `font.family`，颜色只用 `color:`；
   - 名字写错**不会报错**，只会渲染空白。
3. **文字**：需要精确字号/颜色时用 `import QtQuick 2.15 as QQ` + `QQ.Text`；
   `import RinUI` 后的裸 `Text` 是 RinUI 包装件（自带主题色/固定行高），会覆盖自定义配色。
4. **配色跟随模式**：`lessonsBackend.mode === "whiteboard"` → 亮色，否则暗色；
   所有颜色从 `lightMode` 派生（如 `fg = lightMode ? "#000000" : "#FFFFFF"`），不要写死。
5. **弹层生命周期**：重资源（缩略图等）用 `Loader` + `source: open ? "..." : ""`，关闭即销毁；
   关闭时同时清后端缓存（如 `clearDataManagerCache()`）。
6. **不要在高频回调里 new 对象**：画布重绘走 `_redraw_active()`，预览几何现算不落盘。

## 5. 后端约定（`main.py`）

- QML 要调用的方法**必须是 `@Slot(...)`**（`@Property` 用 `notify=` 绑定信号），否则 QML 里调用会静默失败。
- 笔迹模型：每条 stroke = `{op, color, width, points, style, pat, grp, seq}`；
  `style` 为空 = 手绘，`"arrow"` = 线型，`fig:<kind>` = 图形，`grp` 把多笔图形成组（整组选中/一次撤销）。
- 多页与会话：`_pages = [{file, strokes, undo}]`、`_page_index`、注册表 `pages.json`；
  每页一个 `canvas_*.db`；**历史页面 = `data` 目录里未打开的 `canvas_*.db`**。
- **落盘精度**：`points` 的 x,y 存库时统一取 **2 位小数**（`_q_pts()` / `_q2()`，在 `add_stroke` /
  `insert_stroke` / `update_stroke` 三处，`pat` 同规则），pressure 不动；**只在落盘层取整，内存几何保持原精度**
  （否则抛物线的 1e-9 级不变量断言会被打挂）→ 重启/切页读回与内存相差 ≤ 0.005 px，属预期。
- 缩略图：`image://whiteboard/thumb?page=N&v=<thumbVersion>&o=<tick>`（已打开页）、
  `image://whiteboard/hist?file=<name>&v=<mtime>&o=<tick>`（历史页）。
  `v=` / `o=` **仅用于改 URL 让 Qt 图片缓存重新请求**（provider 会忽略它们）→ 新写 `Image.source` 必须带 `&v=`。
- **坐标系（视框 / viewBox 模型，改坐标相关代码前必读）**：
  - **画布坐标**（= SQLite 里的 `points`）= **首次落笔那台屏幕的逻辑像素**，永久不变；
    **视口坐标** = 当前屏幕/窗口逻辑像素（= QML 的 `mouse.x/y`）。
  - `meta` 只存**内容框** `frame_x/y/w/h`（创建时屏幕逻辑尺寸、原点 0,0，**永不修改**）+ 视口快照 `view_*`（仅记录）；
    **不存 `device_pixel_ratio`**，缩放 `viewScale = 屏幕宽 / 视口宽` 现算。
  - 映射：`视口 = (画布 − 视口原点) × viewScale`；分辨率变化时视口 = 内容框补足到新宽高比 + 原点前移 `Δ/2`
    （内容居中、不截断）。推导入口 `_fit_view()`，**每次都从 `frame_*` 现算，不得在旧视口上累加**（会越切越小）。
  - **新增任何 `@Slot`/`@Property` 涉及几何量时**：入参在槽首 `x, y = self._v2c(x, y)`（宽高 `/ self._view_s`），
    出参用 `self._c2v/_c2v_pairs/_c2v_flat`；内部互相调用必须走「画布实现」（`_begin_focus_probe` /
    `_drag_focus_probe` / `_apply_transform`），**不要调回槽**（会二次转换）。
  - 绘制：烘焙图 `_image` 尺寸 = `_canvas_size`（视口），所有 `QPainter(self._image/_plain/预览图)`
    都要 `self._apply_view(painter)`；**图层预烘焙 `_stroke_layer` 不能加变换**（保留整数 blit 优化）。
  - **UI 尺寸必须按屏幕像素恒定**：提示胶囊锚点距离（`_PF_HINT_R = 28`）、端点手柄命中半径（16）
    这类"界面尺寸"写的是**屏幕 px** → 参与画布坐标计算时必须 `/ self._view_s`
    （范例：`_pf_bisect_pt(..., _PF_HINT_R / _view_s)`、`hitLineEndpoint` 里的 `r = 16.0 / _view_s`）。
- 危险区域——改前先读相关测试：
  - **两阶段图形 / 坐标系**：`_tf_*`（3744-3748）、`_ax_*`（3768-3771）是 `WhiteboardBackend` 的**状态字段**，
    **不是方法前缀**（`def _tf_` / `def _ax_` 全文件 0 个，按前缀搜会一无所获）。
    真正入口：`beginFocusProbe` / `dragFocusProbe` / `endFocusProbe` / `finishFocusStage` / `_commit_focus_stage` /
    `_refresh_solid_stage`，坐标系 `_end_axes` / `_move_axes` / `_commit_axes` / `_refresh_axes_stage`；
    两者都由 `beginLine` / `moveLine` / `endLine` 分派。
  - **多边形随心画**：`_pf_begin` / `_refresh_polfree` / `_pf_end_drag` / `_pf_commit_closure` / `_pf_finish`
    （+ 模块级 `_pf_*` 几何辅助）。

## 6. 测试约定

- 测试脚本都在 `_dev/`（gitignored），每个脚本都会 `sys.path.insert(_stub)` + `chdir(_dev)` + 关掉字节码，**不要往仓库根目录写产物**。
- 新功能/修 bug 必须补断言（直接加在对应 `_verify_*.py` 里），断言名写清"验证什么 + 期望值"。
- **打印/断言名里禁止 GBK 不能编码的字符**（典型：`−` U+2212、`²`）→ 用 `-` 和 `^2`，否则控制台 `UnicodeEncodeError`，报错行会指向 `check()` 而看起来像语法错误。
- QML 测试只跑 offscreen，**字体不渲染**（文字测不到，只能断言布局/属性）；视觉问题用截图人工看。
- PySide6 侧读 QML 的注意点：`QQuickWindow` 没有 `childItems()`（要从 `contentItem()` 走）、
  `Loader` 没有 `item()`（按 `objectName` 找）、JS 数组是 `QJSValue`（要 `.toVariant()`）、
  `Rectangle` 的 `border` 分组属性读不到（**把值提成 readonly property 再断言**）。

## 7. 同步安装副本（改完必须做）

1. `main.py`、`qml/**` 直接用 `Copy-Item` 覆盖安装副本里的同名文件；
2. **例外**：`qml/specialmode/ShapeMenu.qml` 的副本里有用户手改的 `chipRow.spacing: 0`（源是 `3`）→
   同步时必须**字节级等长替换**保留（读 `ReadAllBytes` → `spacing: 3` 改成 `spacing: 0` → `WriteAllBytes`），
   不要用 `Set-Content -Encoding UTF8`（会加 BOM、改行尾）；
3. 同步后逐文件比对 MD5 并报给用户；
4. `_dev/` 与测试脚本**永远不要**同步到安装副本。

## 8. Agent 工作流

- 主 Agent（唯一调度者/账本维护者）：`.github/agents/orchestrator.agent.md`
- 子 Agent：`.github/agents/explorer.agent.md`（只读探索）、`.github/agents/reviewer.agent.md`（独立审查）、`.github/agents/releaser.agent.md`（发版）
- 长期记忆：`.github/agents/memory/index.md`（索引 + 硬约束）、`.github/agents/memory/design-system.md`（前端 token）
- 任务账本：`TASK_STATE.md`（每个任务开始填、结束更新）
- 未发布改动日志：`docs/CHANGELOG-unreleased.md`（每轮任务结束追加；发版后由 git-cliff 接管）

**标准顺序**：读 `AGENTS.md` + 记忆 + 账本 →（按需）Explorer → 定契约并实现 →
测试（六套 + render）→ 截图（前端）→（按需）Reviewer → 修复 → 更新账本/日志 → 同步安装副本 → 汇报。

## 9. Git 与发版（硬约束）

- **开发过程中禁止 `git commit` / `git push` / `git tag`**：提交与推送由仓库作者本人完成，Agent 只负责把改动留在工作区并写好日志。
- 发版只在**用户明确要求**时由 `Releaser` agent 执行（改两处版本号 → commit → 打 tag → push 触发 CI）。
- 不手动构建 `.cwplugin` / `.zip`，不手动创建 GitHub Release。

## 10. 每轮任务收尾清单

- [ ] 六套离屏回归全 PASS + `_dev\_render_menu.py` 差异全 0
- [ ] 前端改动：截图自查（`DM_SHOT=1`）
- [ ] 同步安装副本 + 报 MD5
- [ ] 更新 `TASK_STATE.md`（测试结果 / 变更记录 / 未决问题）
- [ ] 仓库事实有变化 → 更新 `AGENTS.md` 和/或 `.github/agents/memory/*`
- [ ] 在 `docs/CHANGELOG-unreleased.md` 追加本轮条目
- [ ] **不提交 git**
