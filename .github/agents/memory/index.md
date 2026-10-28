# 仓库长期记忆 · 索引

> 谁维护：**只有主 Agent（`orchestrator`）能写**；子 Agent 只能建议。
> 读的时机：每次任务开始（本文件必读）；涉及前端时再读 `design-system.md`。
> 与其他文件的分工：`AGENTS.md` 是入口与硬约束，`TASK_STATE.md` 是"这一轮"的账本，
> 这里放**跨轮次仍然成立的事实**（易踩的坑、验证手法、环境事实）。

## 本目录文件

| 文件 | 内容 | 何时读 |
|---|---|---|
| `index.md`（本文件） | 索引 + 硬约束速查（坑、验证手法、外部依赖） | 每个任务开始 |
| `design-system.md` | 前端设计 token：配色、尺寸、圆角、图标、动画参数 | 任何 QML 改动 |

## 硬约束速查（踩过的坑，别再踩）

**QML / Qt**
1. `import RinUI` 后的裸 `Text` 是 RinUI 包装件（自带 `color` / 固定行高）→ 需要精确字号颜色时用 `QQ.Text`（`import QtQuick 2.15 as QQ`）。
2. `Icon` 名字写错**不报错只渲染空白**；只认 `*_20_regular` / `*_20_filled`，必须在 `RinUI/assets/fonts/FluentSystemIcons-Index.js` 里能搜到。
3. `Rectangle` 不支持逐角圆角；`Shape` + `ShapePath` 可以（只给需要的边描边时用"填充路径 + 开放描边路径"两段）。
4. RinUI **没有导出 `ScrollView`**（qmldir 里只有 `ScrollBar` / `ScrollViewer`）→ 要 RinUI 默认滚动条就用 `Flickable` + `ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }`。
5. **不要在信号处理器里同步销毁正在发信号的项**（如 `Loader.source = ""`）：后续 JS 语句会被静默中断 → 先做业务动作，再用 `Qt.callLater()` 卸载。
6. 需要"弹簧滑动"的指示条要用**两端各自跑**的 4 段 `NumberAnimation`（先行端 `OutCubic`、跟随端 `InOutQuad` 且时长更短）；**不要**用 `Behavior` + 按方向绑定 `easing`（绑定只求值一次，反向会错）。
7. 尺寸用整数；`Icon.size` 是 `int`，表达式会被截断（不四舍五入）。

**PySide6 测试侧**
8. `QQuickWindow` 没有 `childItems()` → 从 `win.contentItem()` 走；`Loader` 没有 `item()` → 按 `objectName` 找；
   JS 数组是 `QJSValue` → `.toVariant()`；`Rectangle` 的 `border` 分组属性读不到 → 把值提成 QML `readonly property`。
9. offscreen 下**字体不渲染**：文字相关只能断言 `text` 属性，视觉靠截图人工看。
10. 断言名/打印串里禁止 GBK 不能编码的字符（`−` U+2212、`²` …）→ 用 `-`、`^2`；否则 `UnicodeEncodeError` 会把 traceback 指到 `check()` 上，看着像语法错误。

**同步与环境**
11. 安装副本 `qml/specialmode/ShapeMenu.qml` 里有用户手改的 `chipRow.spacing: 0`（源是 `3`）→ 同步必须**字节级等长替换**保留；不要用 `Set-Content -Encoding UTF8`（加 BOM / 改行尾）。
12. 用户会**直接改安装副本**里的 QML（微调像素）→ 开工前先对比源与副本，必要时先把副本回灌到工作区再改。

## 验证手法（照抄即可）
- 六套回归 + `_dev\_render_menu.py`（「差异采样点: 0」+ 墨量比 ≈1.000）见 `AGENTS.md §3`。
- 像素/几何问题的"对照实验"：先正常跑一遍，再手工复现旧状态，证明断言能抓到原来的 bug（而不是碰巧通过）。
- 加断言前先想清楚**可观测的量**：布局 → 属性/几何；绘制 → 采样点颜色/墨量；交互 → 桩记录的方法调用序列。
- 中文路径下给 QML `Image.source` 传本地文件要用 `QUrl.fromLocalFile(path).toString()`（否则 URL 非 ASCII 可能加载失败）。

## 外部依赖（别改、别打包）
- `_research_extract/`：主程序反编译参考，只读。
- `.venv/Lib/site-packages/RinUI`：第三方 UI 库，**不要改**；需要覆盖就在插件里放同名组件。
- `_dev/`：本机开发工具（gitignored），永不进安装副本。

## 维护规则
- 只写"跨轮次成立"的事实；一次性的调试过程写进当轮 `TASK_STATE.md` 的「变更记录」。
- 与 `AGENTS.md` 重复的条目以 `AGENTS.md` 为准，这里只保留"容易忘、代价高"的。
- 事实变化（新增约束、坑被填平）时**直接改这里**，不要追加历史段落。
