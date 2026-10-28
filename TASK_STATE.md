# Task State

> **本文件是 Agent 工作流的一部分，不是可选的草稿**：
> 任务开始（定契约前）由主 Agent 填「基本信息 / 接口契约 / 文件所有权 / 验收命令」；
> 实现与自测后填「测试结果 / 截图路径」；Reviewer 回填「Reviewer 结论」；
> 收尾时写「变更记录 / 未决问题」。**每轮任务结束必须更新，不要留空占位。**
>
> 字段说明与仓库约定见 `AGENTS.md`；前端 token 见 `.github/agents/memory/design-system.md`。

## 基本信息
- 任务类型: `workflow-doc`（顺带梳理「文件管理页」这一批未提交改动的日志）
- 风险等级: low（只改文档 / agent 说明；不碰 `main.py` 与 QML 逻辑）
- 目标: ① 把 `AGENTS.md`、`TASK_STATE.md` 从通用模板补成本仓库的具体规则；
  ② `.github/agents/releaser.agent.md` 按新版 agent 规范重写（保留原有全部发版约束）；
  ③ 优化 `orchestrator.agent.md` 并修正过时工具名（`runCommands` → `execute/runInTerminal` 等）；
  ④ 把「写 AGENTS.md / TASK_STATE.md / 改动日志」固化为工作流的一环；
  ⑤ 把 `v1.1.0-alpha` 之后的未提交改动整理成 `docs/CHANGELOG-unreleased.md`。


**风险等级判定（本仓库口径）**
- `low`：纯文案、单个 QML 常量微调、`_dev/` 测试脚本改动。
- `medium`：单个 QML 组件布局/配色/动画；不触碰 `_tf_*` / `_ax_*` / `_pf_*` 的后端小改。
- `high`：`main.py` 里的图形/坐标系/多页/存储路径；`main.py` 与 QML 的接口（`@Property`/`@Slot`）；
  文件管理页这类会读写用户数据的模块。

## 接口契约
- 无代码接口变化（纯文档）。新增/固化的"契约"是流程约定：
  - 每轮收尾必须更新 `TASK_STATE.md` + `docs/CHANGELOG-unreleased.md`；仓库事实变化时更新 `AGENTS.md` / `.github/agents/memory/*`。
  - 开发期禁止 `git commit` / `git push` / `git tag`；发版只由 `Releaser` 执行且需用户明确要求。

## 文件所有权
| 文件/目录 | 主责Agent | 状态 |
|---|---|---|
| `AGENTS.md` | Orchestrator | 完成（补全仓库细节） |
| `TASK_STATE.md` | Orchestrator | 完成（模板 + 仓库口径） |
| `.github/agents/orchestrator.agent.md` | Orchestrator | 完成（工具名修正 + 收尾职责） |
| `.github/agents/releaser.agent.md` | Orchestrator | 完成（新版规范重写，内容保留） |
| `.github/agents/reviewer.agent.md` | Orchestrator | 完成（增加账本/日志检查项） |
| `.github/agents/memory/index.md`、`design-system.md` | Orchestrator | 新增 |
| `docs/CHANGELOG-unreleased.md` | Orchestrator | 新增 |


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
- 是否已完成: yes
- 摘要: `AGENTS.md` / `TASK_STATE.md` 之前是通用模板（无仓库细节）；`releaser.agent.md` 用的是旧 frontmatter
  （无 `name`、`tools` 写成 `[read, edit, search, execute]`）；`orchestrator.agent.md` 的工具名 `runCommands` 已废弃，
  且引用的 `.github/agents/memory/*` 原本不存在（悬空引用）。
- 关键文件/行号: `.github/agents/*.agent.md`（23 行左右 frontmatter）、`cwplugin.json`（name/description 已更名）、
  `main.py`（+9.1k 行手写板后端）、`qml/specialmode/**`（新目录 18 个文件）
- 基线: 最后一个提交 `93a6620`（tag `v1.1.0-alpha`）

## 测试结果
- 命令: `python -m py_compile main.py` + 六套 `_dev/_verify_*.py` + `_dev/_render_menu.py`
- 结果: compile=0；六套全部「无 —— 全部通过」；render exit=0（差异采样点 0、墨量比 ≈1.000）
- 时间: 2026-10-28


## 截图路径（前端）
- 面板/弹层: `_dev/_dev_out/datamanager.png`、`datamanager_panel.png`、`datamanager_zoom.png`（2×）
- 其他:

## Reviewer 结论
- 状态: 未审
- 轮次: 0
- 阻断项:
- 放行条件:

## 未决问题
- `v1.1.0-alpha` 之后的改动仍未提交 git（由作者提交；`docs/CHANGELOG-unreleased.md` 已备好摘要）。
- `libs/` 未跟踪，需确认是运行期依赖（不入库）还是应随仓库提交。
- 文件管理页「保存 / 另存至 / 导出图片」三个选项卡仍是占位，功能未实装。
- `qml/specialmode/EraserMenu.qml` 源与安装副本历史上排版不一致，现已按源同步；如要以副本为准需另行告知。

## 变更记录
- 2026-10-28 · 工作流文档落地（`AGENTS.md` 补全目录/命令/QML 与后端约定/同步副本/收尾清单；
  `TASK_STATE.md` 补仓库口径的风险分级与验收命令；`releaser.agent.md` 按新版规范重写；
  `orchestrator.agent.md` 修正工具名并加"收尾三件套/不提交 git"；新增 `.github/agents/memory/{index,design-system}.md`
  与 `docs/CHANGELOG-unreleased.md`）· 未改代码，六套回归 + render 全 PASS。
- 2026-10-28 · `docs/CHANGELOG-unreleased.md` 扩写：补上更早期改动（换课按钮、悬停渐隐、迷你模式适配、
  平板适配、主程序设置页入口、新增设置项、预备时段高亮修复），并按"不写像素/参数微调、不单列新功能的后续修补"
  的口径重排；基线核对到 `v1.1.0-alpha`（`main.py` 3021 → 12001 行）。

