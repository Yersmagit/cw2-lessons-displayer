<div align="center">
<img src="icon.png" width="192px" alt="Lessons Displayer">
<h1>Lessons Displayer</h1>

<p>看看今天有什么课？</p>

<!--[![当前版本](https://img.shields.io/github/v/release/Yersmagit/cw2-lessons-displayer?style=for-the-badge&color=purple&label=%E5%BD%93%E5%89%8D%E7%89%88%E6%9C%AC)](https://github.com/Yersmagit/cw2-lessons-displayer/releases/latest)--->

[![星标](https://img.shields.io/github/stars/Yersmagit/cw2-lessons-displayer?style=for-the-badge&color=orange&label=%E6%98%9F%E6%A0%87)](https://github.com/Yersmagit/cw2-lessons-displayer)
[![开源许可](https://img.shields.io/badge/license-MIT-blue.svg?label=%E5%BC%80%E6%BA%90%E8%AE%B8%E5%8F%AF%E8%AF%81&style=for-the-badge)](https://github.com/Yersmagit/cw2-lessons-displayer)
[![下载量](https://img.shields.io/github/downloads/Yersmagit/cw2-lessons-displayer/total.svg?label=%E4%B8%8B%E8%BD%BD%E9%87%8F&color=green&style=for-the-badge)](https://github.com/Yersmagit/cw2-lessons-displayer)

</div>

> [!TIP]
> 
> **插件现已更新到正式版！**

## 📖 简介 / Introduction
- 可以完全展示当日课程信息，完全杜绝抄课表。
本插件适用于 [Class Widgets 2](https://github.com/rinlit-233-shiroko/class-widgets-2) 。

### ✨ 特性 / Features
- 显示当日课程信息
- 提供全屏白板模式和熄屏模式


## 📦 功能 / Functions
### 主组件 / Main Widget
- 软件运行时，自动显示当日课程信息。
  <div style="text-align: center;">
  <img src="previews/ex_default.png" alt="ex_default" style="max-width:100%; height:auto;">
  </div>

- 当前正在进行的课程或即将进行的课程会高亮显示，高亮颜色分别为橙红色和绿色。
  比如，数学课上课时，就是这样显示的：
  <div style="text-align: center;">
  <img src="previews/ex_on_class.png" alt="ex_on_class" style="max-width:100%; height:auto;">
  </div>

- 在当日空闲时段，会自动显示一个 **分割线** 分隔课程。
  <div style="text-align: center;">
  <img src="previews/ex_divider.png" alt="ex_divider" style="max-width:100%; height:auto;">
  </div>

  *注：需要空闲时段超过 15 分钟*

> [!TIP]
> 
> 课程列表支持滚动。同时，插件也会自动把重要内容滚动到左侧。

> [!IMPORTANT]
> 
> 未来，我们将在此小组件上展示更多内容。例如：明日课程、长通知、天气预警、集控相关信息等。

### 特殊模式 / Special Modes
- <span style="display: inline-flex; align-items: center; white-space: nowrap; gap: 4px;"><span>小组件右侧，有 <strong>白板模式</strong> 按钮</span> <img src="previews/ex_light_bottom.png" alt="ex_light_bottom" style="width:30px; height:30px; border-radius: 50%;"> <span>和 <strong>熄屏模式</strong> 按钮</span> <img src="previews/ex_dark_bottom.png" alt="ex_dark_bottom" style="width:30px; height:30px; border-radius: 50%;"></span>

  单击相应按钮以切换模式。

- 在白板模式或熄屏模式，只有关键信息被展示，界面全屏纯净，类似屏保。
  <div style="text-align: center;">
  <img src="previews/ex_blackboard.png" alt="ex_blackboard" style="max-width:100%; height:auto;">
  </div>

  此时，当前课程的位置会显示更多信息。
  <div style="text-align: center;">
  <img src="previews/ex_lessons_in_blackboard.png" alt="ex_lessons_in_blackboard" style="max-width:100%; height:auto;">
  </div>

### 设置页 / Settings
- 插件提供设置页，这里有更多你想要的功能！
  <div style="text-align: center;">
  <img src="previews/ex_settings.png" alt="ex_settings" style="max-width:100%; height:auto;">
  </div>

> [!TIP]
> 
> 设置页打开方式：
> 1. 在小组件形态时，直接右键/长按小组件，打开右键菜单，选择“设置”。
> 2. 在熄屏/白板模式下，右键/长按屏幕上的任意位置，打开右键菜单，选择“设置”。

## 📥 安装 / Installation
### 如何安装并启用 / How to Install and Enable
1. 下载插件包

2. 在 Class Widgets 2 > "设置" > "插件"中导入下载好的插件包

3. 在 Class Widgets 2 > "设置" > "插件"中启用

4. 重启软件

5. 完成！

## 🤔 反馈 / Feedback

有功能建议或遇到问题？欢迎在 [GitHub Issues](https://github.com/Yersmagit/cw2-lessons-displayer/issues) 中指出！

## 📘 其它 / Others
### 引用资源 / Credits
- [Class Widgets 2](https://github.com/rinlit-233-shiroko/class-widgets-2)
- [Class Widgets 2 SDK](https://github.com/Class-Widgets/class-widgets-sdk)
- [RinUI](https://ui.rinlit.cn/)

### 版权 / License
本项目基于 MIT 协议开源，详情请参阅 [LICENSE](https://github.com/rinlit-233-shiroko/class-widgets-2-plugin-template/blob/main/LICENSE) 文件。

The project is licensed under the MIT license. Please refer to the [LICENSE](https://github.com/rinlit-233-shiroko/class-widgets-2-plugin-template/blob/main/LICENSE) file for details.
