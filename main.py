"""
Class Widgets 2.0 - 今日课程显示插件 (独立全屏窗口版)
显示当日所有课程缩写，并高亮当前课程，使用mask仅显示UI区域
"""

import os
import sys
import ctypes
import darkdetect
from loguru import logger
from PySide6.QtCore import QObject, QUrl, Slot, Property, Signal, QTimer
from PySide6.QtGui import QGuiApplication, QScreen, QRegion, QCursor
from PySide6.QtQml import QQmlApplicationEngine
from ClassWidgets.SDK import CW2Plugin
from PySide6.QtCore import Qt

plugin_logger = logger.bind(plugin="lessons-displayer")

# 默认宽度常量
DEFAULT_UI_WIDTH = 100
UI_HEIGHT = 54

# 自动关闭特殊模式功能开关
AUTO_CLOSE_SPECIAL_MODE_ENABLED = True  # 设为 False 可禁用


def _time_to_minutes(time_str: str) -> int:
    """将 "HH:MM" 格式的时间转换为分钟数"""
    h, m = map(int, time_str.split(':'))
    return h * 60 + m


class LessonsBackend(QObject):
    lessonsUpdated = Signal()
    themeChanged = Signal(bool)
    positionChanged = Signal()
    widthChanged = Signal()
    opacityChanged = Signal()
    scrollRequested = Signal(int)
    modeChanged = Signal()
    fontChanged = Signal()  
    bgOpacityChanged = Signal()
    scaleFactorChanged = Signal()
    switchingChanged = Signal()

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self._lessons = []
        self._display_items = []
        self._current_lesson_id = ""
        self._next_lesson_id = ""
        self._current_state = 0
        self._is_dark = False
        self._ui_x = 0
        self._ui_y = 0
        self._ui_width = DEFAULT_UI_WIDTH
        self._opacity = 0
        self._mode = "normal"
        self._current_icon = "ic_fluent_question_20_regular"
        self._current_remaining_text = ""
        self._font_family = ""
        self._font_weight = 400

        # 自动关闭特殊模式相关
        self._auto_close_timer = QTimer()
        self._auto_close_timer.timeout.connect(self._on_auto_close_timeout)
        self._auto_close_timer.setSingleShot(True)
        self._in_auto_close_status = False

        # 特殊模式窗口切换标记（切换期间禁用按钮，防止误操作）
        self._switching = False

        # 移除窗口 mask 的引用计数（右键菜单/文本提示可同时占用，归零才恢复）
        self._mask_hide_refs = 0

        # 初始化字体
        self._update_font()

        # 初始化背景不透明度
        self._bg_opacity = 1.0
        self._update_bg_opacity
        
        # 初始化缩放因子
        self._scale_factor = 1.0
        self._update_scale_factor()


    def set_ui_opacity(self, opacity):
        if opacity != self._opacity:
            self._opacity = opacity
            self.opacityChanged.emit()

    def _update_bg_opacity(self):
        try:
            configs = self.plugin._configs
            if configs:
                self._bg_opacity = getattr(configs.preferences, 'opacity', 1.0)
            else:
                self._bg_opacity = 1.0
        except Exception:
            self._bg_opacity = 1.0
        self.bgOpacityChanged.emit()

    def _update_scale_factor(self):
        try:
            configs = self.plugin._configs
            if configs:
                self._scale_factor = getattr(configs.preferences, 'scale_factor', 1.0)
            else:
                self._scale_factor = 1.0
        except Exception:
            self._scale_factor = 1.0
        self.scaleFactorChanged.emit()

    def _update_font(self):
        """从配置更新字体和字重"""
        try:
            configs = self.plugin._configs
            if configs:
                prefs = configs.preferences
                self._font_family = getattr(prefs, 'font', 'Microsoft YaHei')
                self._font_weight = getattr(prefs, 'font_weight', 600)
            else:
                self._font_family = "Microsoft YaHei"
                self._font_weight = 600
        except Exception as e:
            plugin_logger.debug(f"读取字体配置失败: {e}，使用默认值")
            self._font_family = "Microsoft YaHei"
            self._font_weight = 600
        self.fontChanged.emit()

    def _get_entry_full_name(self, entry):
        """获取条目的全称"""
        entry_type = entry.get("type", "")
        if entry_type == "class":
            subject_id = entry.get("subjectId")
            if subject_id and subject_id in self.plugin._subjects_name_map:
                return self.plugin._subjects_name_map[subject_id]
            return "课程"
        elif entry_type == "activity":
            title = entry.get("title", "")
            if title:
                return title
            return "活动"
        elif entry_type == "break":
            return "课间"
        elif entry_type == "preparation":
            return "预备"
        else:
            return "未知"

    def update_lessons(self):
        entries = self.plugin.api.runtime.current_day_entries
        if not entries:
            self._lessons = []
            self._display_items = [{
                "type": "placeholder",
                "icon": "ic_fluent_text_bullet_list_dismiss_20_regular",
                "text": "今天还没有课程 ~"
            }]
            self._current_lesson_id = ""
            self._next_lesson_id = ""
            self.lessonsUpdated.emit()
            plugin_logger.info("没有课程需要显示，添加占位提示")
            return

        self.plugin._update_subjects_map()

        all_entries = entries
        n = len(all_entries)

        def should_show(entry):
            e_type = entry.get("type", "")
            if e_type == "break":
                return False
            if e_type == "activity" and entry.get("title") in ["大课间", "升旗", "晚读/晚练", "备考", "进考场"]:
                return False
            return True

        show_flags = [should_show(e) for e in all_entries]

        display_items = []
        lessons = []
        filtered_ids = set()

        last_displayed_end = None

        for i, entry in enumerate(all_entries):
            if not show_flags[i]:
                continue

            entry_id = entry.get("id", "")
            entry_type = entry.get("type", "")
            title = entry.get("title", "")
            abbr = self.plugin._get_entry_abbr(entry)
            full_name = self._get_entry_full_name(entry)
            is_class = (entry_type == "class")

            if last_displayed_end is not None:
                current_start = _time_to_minutes(entry.get("startTime"))
                gap = current_start - last_displayed_end
                if gap >= 15:
                    display_items.append({"type": "separator"})

            lesson_item = {
                "type": "lesson",
                "id": entry_id,
                "abbr": abbr,
                "fullName": full_name,
                "isClass": is_class
            }
            display_items.append(lesson_item)
            lessons.append(lesson_item)
            filtered_ids.add(entry_id)

            last_displayed_end = _time_to_minutes(entry.get("endTime"))

        if not display_items:
            display_items.append({
                "type": "placeholder",
                "icon": "ic_fluent_text_bullet_list_dismiss_20_regular",
                "text": "今天还没有课程 ~"
            })

        self._display_items = display_items
        self._lessons = lessons

        current = self.plugin.api.runtime.current_entry
        if current and current.get("type") == "class":
            self._current_lesson_id = current.get("id", "")
        else:
            self._current_lesson_id = ""

        next_lesson_id = ""
        next_entries = self.plugin.api.runtime.next_entries
        if next_entries:
            for ne in next_entries:
                if ne.get("id") in filtered_ids and ne.get("type") == "class":
                    next_lesson_id = ne.get("id", "")
                    break
        self._next_lesson_id = next_lesson_id

        self._current_state = 1 if self.plugin.api.runtime.current_status == "class" else 0
        self.lessonsUpdated.emit()

        self._update_current_icon_and_remaining()
        self._check_auto_close()

    def _check_auto_close(self):
        """检查是否满足自动关闭特殊模式的条件"""
        current_status = self.plugin.api.runtime.current_status
        is_auto_close_status = current_status in ("break", "activity", "free")
        if is_auto_close_status:
            if not self._in_auto_close_status:
                self._in_auto_close_status = True
                self._auto_close_timer.start(180000)
        else:
            if self._in_auto_close_status:
                self._in_auto_close_status = False
                self._auto_close_timer.stop()

    def _on_auto_close_timeout(self):
        """自动关闭超时处理"""
        if self._mode != "normal" and AUTO_CLOSE_SPECIAL_MODE_ENABLED:
            self.exitSpecialMode()
            plugin_logger.info("自动关闭特殊模式：课间/活动持续180秒")

    def _update_current_icon_and_remaining(self):
        """更新当前活动的图标和剩余时间文本"""
        current_entry = self.plugin.api.runtime.current_entry

        if current_entry:
            subject_id = current_entry.get("subjectId")
            if subject_id:
                try:
                    schedule = self.plugin.api._app.schedule_manager.schedule
                    if schedule and hasattr(schedule, 'subjects'):
                        for subj in schedule.subjects:
                            if subj.id == subject_id and subj.icon:
                                self._current_icon = subj.icon
                                break
                        else:
                            e_type = current_entry.get("type", "")
                            if e_type == "class":
                                self._current_icon = "ic_fluent_class_20_regular"
                            elif e_type == "break":
                                self._current_icon = "ic_fluent_shifts_activity_20_filled"
                            elif e_type == "activity":
                                self._current_icon = "ic_fluent_alert_20_regular"
                            elif e_type == "preparation":
                                self._current_icon = "ic_fluent_hourglass_half_20_regular"
                            else:
                                self._current_icon = "ic_fluent_question_20_regular"
                except Exception as e:
                    plugin_logger.debug(f"获取科目图标失败: {e}")
                    self._current_icon = "ic_fluent_question_20_regular"
            else:
                e_type = current_entry.get("type", "")
                if e_type == "class":
                    self._current_icon = "ic_fluent_class_20_regular"
                elif e_type == "break":
                    self._current_icon = "ic_fluent_shifts_activity_20_filled"
                elif e_type == "activity":
                    self._current_icon = "ic_fluent_alert_20_regular"
                elif e_type == "preparation":
                    self._current_icon = "ic_fluent_hourglass_half_20_regular"
                else:
                    self._current_icon = "ic_fluent_question_20_regular"
        else:
            self._current_icon = "ic_fluent_accessibility_20_regular"

        remaining = self.plugin.api.runtime.remaining_time
        if not remaining:
            self._current_remaining_text = ""
            return

        minutes = remaining.get("minute", 0)
        seconds = remaining.get("second", 0)
        total_seconds = minutes * 60 + seconds

        if total_seconds < 60:
            secs = max(1, total_seconds)
            if self._current_state == 1:
                self._current_remaining_text = f"剩 {secs} 秒"
            else:
                self._current_remaining_text = f"{secs} 秒后上课"
        else:
            mins = round(total_seconds / 60)
            if self._current_state == 1:
                self._current_remaining_text = f"剩 {mins} 分钟"
            else:
                self._current_remaining_text = f"{mins} 分钟后上课"

    def set_dark_theme(self, is_dark):
        if self._is_dark != is_dark:
            self._is_dark = is_dark
            self.themeChanged.emit(is_dark)

    def set_ui_width(self, width):
        if width != self._ui_width and width > 0:
            self._ui_width = width
            self.widthChanged.emit()
            self.update_position()

    def update_position(self):
        try:
            configs = self.plugin._configs
            prefs = configs.preferences
            interactions = configs.interactions
            anchor = prefs.widgets_anchor
            offset_x = prefs.widgets_offset_x
            offset_y = prefs.widgets_offset_y
            hide = interactions.hide.state

            scale_factor = prefs.scale_factor if hasattr(prefs, 'scale_factor') else 1.0
            mini_mode = prefs.mini_mode if hasattr(prefs, 'mini_mode') else False
            base_height = 56 if mini_mode else 100
            widgets_height = base_height * scale_factor

            screen = QGuiApplication.primaryScreen().availableGeometry()
            screen_width = screen.width()
            screen_height = screen.height()
            ui_width = self._ui_width

            parts = anchor.split("_")
            if len(parts) != 2:
                x = (screen_width - ui_width) // 2
                y = 132
            else:
                vert, horz = parts[0].lower(), parts[1].lower()

                if vert == "top":
                    if hide and horz == "center":
                        y = -UI_HEIGHT + 24
                    else:
                        y = 8 + widgets_height + offset_y
                elif vert == "bottom":
                    if hide and horz == "center":
                        y = screen_height - 24
                    else:
                        y = screen_height - UI_HEIGHT - offset_y - widgets_height + 40
                else:
                    y = 132

                if horz == "left":
                    if hide:
                        x = -ui_width + 24
                    else:
                        x = offset_x
                elif horz == "right":
                    if hide:
                        x = screen_width - 24
                    else:
                        x = screen_width - ui_width - offset_x
                elif horz == "center":
                    x = (screen_width - ui_width) // 2 + offset_x
                else:
                    x = (screen_width - ui_width) // 2

            self._ui_x = int(x)
            self._ui_y = int(y)
            self.positionChanged.emit()

            new_opacity = 0 if hide else 1
            self.set_ui_opacity(new_opacity)

        except Exception as e:
            plugin_logger.error(f"计算位置失败: {e}")
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self._ui_x = (screen.width() - self._ui_width) // 2
            self._ui_y = 132
            self.positionChanged.emit()
            self.set_ui_opacity(1)

    def request_scroll_to_current(self):
        target_id = self._current_lesson_id or self._next_lesson_id
        if not target_id:
            return
        for i, lesson in enumerate(self._lessons):
            if lesson["id"] == target_id:
                for idx, item in enumerate(self._display_items):
                    if item.get("type") == "lesson" and item.get("id") == target_id:
                        self.scrollRequested.emit(idx)
                        break
                break

    def _set_mode(self, mode):
        if self._mode != mode:
            self._mode = mode
            self.modeChanged.emit()

    @Slot()
    def enterWhiteboard(self):
        self._set_mode("whiteboard")

    @Slot()
    def enterBlackboard(self):
        self._set_mode("blackboard")

    @Slot()
    def exitSpecialMode(self):
        self._set_mode("normal")

    @Slot()
    def hideWidgetMask(self):
        """请求移除窗口 mask（引用计数：右键菜单 / 按钮文本提示可同时占用）。
        仅正常模式真正操作 mask；所有模式都累计引用计数，避免相互覆盖。"""
        try:
            self._mask_hide_refs += 1
            if self.plugin.window and self.mode == "normal":
                self.plugin._mask_enabled = False
                self.plugin.window.setMask(QRegion())
        except Exception as e:
            plugin_logger.debug(f"移除 mask 失败: {e}")

    @Slot()
    def showWidgetMask(self):
        """释放 mask 占用；引用计数归零且处于正常模式时恢复窗口 mask。"""
        try:
            self._mask_hide_refs = max(0, self._mask_hide_refs - 1)
            if self.plugin.window and self.mode == "normal" and self._mask_hide_refs == 0:
                self.plugin._mask_enabled = True
                self.plugin._update_mask()
        except Exception as e:
            plugin_logger.debug(f"恢复 mask 失败: {e}")

    @Slot(result=bool)
    def isUiAboveTaskbar(self):
        """检测当前 UI 是否位于任务栏上层（供 QML 监测/调试用）"""
        try:
            return self.plugin._is_above_taskbar()
        except Exception:
            return True

    @Property(str, notify=modeChanged)
    def mode(self):
        return self._mode

    @Property(int, notify=positionChanged)
    def uiX(self):
        return self._ui_x

    @Property(int, notify=positionChanged)
    def uiY(self):
        return self._ui_y

    @Property(int, notify=widthChanged)
    def uiWidth(self):
        return self._ui_width

    @Property(float, notify=opacityChanged)
    def uiOpacity(self):
        return self._opacity

    @Property(list, notify=lessonsUpdated)
    def displayItems(self):
        return self._display_items

    @Property(str, notify=lessonsUpdated)
    def currentLessonId(self):
        return self._current_lesson_id

    @Property(str, notify=lessonsUpdated)
    def nextLessonId(self):
        return self._next_lesson_id

    @Property(int, notify=lessonsUpdated)
    def currentState(self):
        return self._current_state

    @Property(bool, notify=themeChanged)
    def isDarkTheme(self):
        return self._is_dark

    @Property(str, notify=lessonsUpdated)
    def currentIcon(self):
        return self._current_icon

    @Property(str, notify=lessonsUpdated)
    def currentRemainingText(self):
        return self._current_remaining_text

    @Property(str, notify=fontChanged)
    def fontFamily(self):
        return self._font_family

    @Property(int, notify=fontChanged)
    def fontWeight(self):
        return self._font_weight
    
    @Property(float, notify=bgOpacityChanged)
    def bgOpacity(self):
        return self._bg_opacity

    @Property(float, notify=scaleFactorChanged)
    def scaleFactor(self):
        return self._scale_factor

    def set_switching(self, value):
        """设置窗口切换标记（切换期间禁用按钮，防止误操作）"""
        if value != self._switching:
            self._switching = bool(value)
            self.switchingChanged.emit()

    @Property(bool, notify=switchingChanged)
    def switching(self):
        return self._switching


class Plugin(CW2Plugin):
    def __init__(self, api):
        super().__init__(api)
        self._subjects_map = {}
        self._subjects_name_map = {}
        self.backend = None
        self.is_dark_theme = False
        self.engine = None
        self.window = None
        self.ui_item = None
        self.ui_loader = None
        self._ui_ready_checked = False
        self._layer_timer = None
        self._width_timer = None
        self._scroll_timer = None
        self._configs = None
        self._mask_enabled = True

        # 特殊模式专用全屏窗口（进入特殊模式后重建，以全新状态置顶显示）
        self.special_engine = None
        self.special_window = None

        self._cursor_timer = QTimer()
        self._cursor_timer.timeout.connect(self._check_mouse_idle)
        self._last_mouse_pos = None
        self._idle_seconds = 0
        self._cursor_hidden = False

        plugin_logger.info("今日课程插件初始化完成")

    def _setup_logging(self):
        try:
            log_dir = os.path.join(self.PATH, "log")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, "lessons-displayer.log")
            logger.add(
                log_file,
                rotation="1 MB",
                retention="7 days",
                encoding="utf-8",
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
                level="DEBUG",
                filter=lambda record: record["extra"].get("plugin") == "lessons-displayer"
            )
            plugin_logger.debug(f"日志文件已创建: {log_file}")
        except Exception as e:
            plugin_logger.error(f"设置插件日志失败: {e}")

    def on_load(self):
        self.api.set_current_plugin(self)
        self._setup_logging()
        plugin_logger.info("今日课程插件加载成功")

        self.api.runtime.updated.connect(self.on_runtime_updated)
        self.api.theme.changed.connect(self.on_theme_changed)
        plugin_logger.debug("已连接 theme.changed 信号")

        self._update_subjects_map()

        try:
            sys_theme = darkdetect.theme()
            self.is_dark_theme = (sys_theme == "Dark")
            plugin_logger.debug(f"通过 darkdetect 获取初始主题: {sys_theme}, 深色模式: {self.is_dark_theme}")
        except Exception as e:
            self.is_dark_theme = False
            plugin_logger.debug(f"无法获取系统主题，使用默认浅色，错误: {e}")

        self._configs = self.api._app.configs
        self._configs.configChanged.connect(self._on_config_changed)
        plugin_logger.debug("已连接 configChanged 信号")

        self.backend = LessonsBackend(self)
        self.backend.update_lessons()
        self.backend.set_dark_theme(self.is_dark_theme)
        self.backend.update_position()
        self.backend.modeChanged.connect(self._on_mode_changed)
        plugin_logger.debug("已连接 modeChanged 信号")

        self.backend.positionChanged.connect(self._update_mask)
        self.backend.widthChanged.connect(self._update_mask)

        self.engine = QQmlApplicationEngine()
        self.engine.rootContext().setContextProperty("lessonsBackend", self.backend)

        qml_path = os.path.join(self.PATH, "qml", "FullScreenWindow.qml")
        plugin_logger.debug(f"加载 QML 文件: {qml_path}")
        qml_url = QUrl.fromLocalFile(qml_path)
        self.engine.load(qml_url)

        if self.engine.rootObjects():
            self.window = self.engine.rootObjects()[0]
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self.window.setProperty("screenWidth", screen.width())
            self.window.setProperty("screenHeight", screen.height())

            self.window.setFlag(Qt.FramelessWindowHint, True)
            self.window.setColor(Qt.transparent)

            self.window.uiReady.connect(self._on_ui_ready)
            plugin_logger.debug("已连接 uiReady 信号")

            # 特殊模式启动动画播放完成后，显示已准备好的专用窗口
            try:
                self.window.specialAnimationFinished.connect(self._on_special_animation_finished)
                plugin_logger.debug("已连接 specialAnimationFinished 信号")
            except Exception as e:
                plugin_logger.debug(f"连接 specialAnimationFinished 失败: {e}")

            QTimer.singleShot(5000, self._check_ui_ready_timeout)

            plugin_logger.info("全屏窗口已创建（隐藏状态）")
        else:
            plugin_logger.error("无法创建全屏窗口")

        self._start_theme_polling()
        self._start_layer_sync()
        self._start_scroll_timer()

    def _on_config_changed(self):
        plugin_logger.debug("配置变化，更新位置、背景不透明度和字体")
        if self.backend:
            self.backend.update_position()
            self.backend._update_font()
            self.backend._update_bg_opacity()
            self.backend._update_scale_factor()

    def _start_layer_sync(self):
        self._layer_timer = QTimer()
        self._layer_timer.timeout.connect(self._sync_window_layer)
        self._layer_timer.start(1000)
        plugin_logger.debug("已启动窗口层级同步定时器")

    def _sync_window_layer(self):
        if not self.window or not self.backend:
            return
        if self.backend.mode != "normal":
            # 特殊模式下持续强制置顶，防止窗口层级被重置导致任务栏露出
            self._force_topmost()
            return
        try:
            main_window = self.api._app.widgets_window
            if not main_window or not main_window.isVisible():
                return

            main_flags = main_window.flags()
            our_flags = self.window.flags()

            new_flags = our_flags & ~(Qt.WindowStaysOnTopHint | Qt.WindowStaysOnBottomHint)

            if main_flags & Qt.WindowStaysOnTopHint:
                pass
            elif main_flags & Qt.WindowStaysOnBottomHint:
                new_flags |= Qt.WindowStaysOnBottomHint

            if new_flags != our_flags:
                self.window.setFlags(new_flags)
                plugin_logger.debug(f"窗口标志已更新: {new_flags}")

            self.window.lower()
        except Exception as e:
            plugin_logger.debug(f"同步窗口层级失败: {e}")

    def _start_theme_polling(self):
        self._theme_timer = QTimer()
        self._theme_timer.timeout.connect(self._check_system_theme)
        self._theme_timer.start(1000)
        plugin_logger.debug("已启动主题轮询定时器")

    def _check_system_theme(self):
        try:
            sys_theme = darkdetect.theme()
            is_dark = (sys_theme == "Dark")
            if is_dark != self.is_dark_theme:
                plugin_logger.debug(f"系统主题变化: {sys_theme}, 深色模式: {is_dark}")
                self.is_dark_theme = is_dark
                if self.backend:
                    self.backend.set_dark_theme(is_dark)
        except Exception as e:
            pass

    def _start_width_polling(self):
        self._width_timer = QTimer()
        self._width_timer.timeout.connect(self._update_widgets_width)
        self._width_timer.start(500)
        plugin_logger.debug("已启动小组件宽度轮询定时器")

    def _update_widgets_width(self):
        if not self.ui_item:
            return
        try:
            root_window = self.api._app.widgets_window.root_window
            if not root_window:
                return
            loader = root_window.findChild(QObject, "widgetsLoader")
            if not loader:
                return

            children = loader.childItems()
            if not children:
                return

            valid_children = []
            for child in children:
                obj_name = child.objectName()
                width = child.width()
                if obj_name != "addWidgetsContainer" and width > 0:
                    valid_children.append(child)

            if not valid_children:
                return

            last_child = valid_children[-1]
            total_width = int(last_child.x() + last_child.width())

            if total_width > 0 and self.backend:
                if total_width != self.backend._ui_width:
                    self.backend.set_ui_width(total_width)
        except Exception as e:
            plugin_logger.debug(f"计算小组件宽度失败: {e}")

    def _start_scroll_timer(self):
        self._scroll_timer = QTimer()
        self._scroll_timer.timeout.connect(self._request_scroll)
        self._scroll_timer.start(1000)
        plugin_logger.debug("已启动滚动请求定时器")

    def _request_scroll(self):
        if self.backend:
            self.backend.request_scroll_to_current()

    def _check_ui_ready_timeout(self):
        if not hasattr(self, 'ui_item') or not self.ui_item:
            plugin_logger.error("uiReady 信号未在 5 秒内触发，Loader 可能加载失败")
            if self.window:
                plugin_logger.debug(f"窗口对象有效，flags: {self.window.flags()}")
                children = self.window.children()
                plugin_logger.debug(f"窗口共有 {len(children)} 个子对象")
                for i, child in enumerate(children):
                    obj_name = child.objectName()
                    class_name = child.metaObject().className()
                    plugin_logger.debug(f"  [{i}] {class_name}: {obj_name}")

                loader = self.window.findChild(QObject, "uiLoader")
                if loader:
                    status = loader.property("status")
                    error_str = loader.property("errorString")
                    plugin_logger.error(f"Loader status: {status} (0=Null,1=Ready,2=Loading,3=Error), error: {error_str}")
                else:
                    plugin_logger.error("无法找到 uiLoader")
            else:
                plugin_logger.error("窗口对象无效")

    def _on_ui_ready(self):
        plugin_logger.debug("_on_ui_ready 被调用")
        try:
            loader = self.window.findChild(QObject, "uiLoader")
            if not loader:
                plugin_logger.error("无法找到 uiLoader")
                return

            self.ui_loader = loader
            self.ui_item = loader.property("item")
            if not self.ui_item:
                plugin_logger.error("UI 项未加载")
                return

            x = self.ui_item.x()
            y = self.ui_item.y()
            w = self.ui_item.width()
            h = self.ui_item.height()
            plugin_logger.debug(f"UI 项初始位置: ({x}, {y}, {w}, {h})")

            self.ui_loader.xChanged.connect(self._update_mask)
            self.ui_loader.yChanged.connect(self._update_mask)
            self.ui_loader.widthChanged.connect(self._update_mask)
            self.ui_loader.heightChanged.connect(self._update_mask)

            self._update_mask()

            hide = self._configs.interactions.hide.state
            self.backend.set_ui_opacity(0)

            def show_and_fade():
                self.window.show()
                plugin_logger.info("窗口已显示，开始淡入")
                self.backend.set_ui_opacity(0)
                target = 0 if hide else 1
                QTimer.singleShot(50, lambda: self.backend.set_ui_opacity(target))

            QTimer.singleShot(0, show_and_fade)

            self._sync_window_layer()
            self._start_width_polling()

            plugin_logger.info("UI 已加载，mask 更新连接已建立")
        except Exception as e:
            plugin_logger.error(f"处理 UI 就绪失败: {e}")

    def _update_mask(self):
        if not self.window:
            return
        if self.backend and self.backend.mode != "normal":
            self.window.setMask(QRegion())
            return
        if not self._mask_enabled:
            return
        try:
            if self.ui_loader:
                x = int(self.ui_loader.property("x"))
                y = int(self.ui_loader.property("y"))
                w = int(self.ui_loader.property("width"))
                h = int(self.ui_loader.property("height"))
            elif self.backend:
                x = int(self.backend.uiX)
                y = int(self.backend.uiY)
                w = int(self.backend.uiWidth)
                h = UI_HEIGHT
            else:
                return
            region = QRegion(x, y, w, h)
            self.window.setMask(region)
        except Exception as e:
            plugin_logger.error(f"更新 mask 失败: {e}")

    def _check_mouse_idle(self):
        """检查鼠标是否空闲，用于特殊模式下自动隐藏光标"""
        if not self.window or self.backend.mode == "normal":
            return
        pos = QCursor.pos()
        if self._last_mouse_pos == pos:
            self._idle_seconds += 0.5
            if self._idle_seconds >= 4.0 and not self._cursor_hidden:
                self.window.setCursor(Qt.BlankCursor)
                self._cursor_hidden = True
        else:
            self._last_mouse_pos = pos
            self._idle_seconds = 0
            if self._cursor_hidden:
                self.window.setCursor(Qt.ArrowCursor)
                self._cursor_hidden = False

    def _enable_mask_and_update(self):
        """延迟后恢复 mask 更新"""
        self._mask_enabled = True
        self._update_mask()

    def _make_foreground_window(self, hwnd):
        """将窗口设为系统前台窗口（绕过 Windows 前台锁定）

        任务栏由系统按"前台窗口"管理：只有前台窗口是全屏置顶窗口时，
        任务栏才会保持在窗口下方。若其它窗口（如资源管理器）是前台，
        任务栏会浮在置顶窗口之上。这里用 AttachThreadInput 技巧绕过
        前台锁定，确保可靠地置为前台。
        """
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            if user32.GetForegroundWindow() == hwnd:
                return
            current_tid = kernel32.GetCurrentThreadId()
            fg_hwnd = user32.GetForegroundWindow()
            fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
            attached = False
            if fg_tid and fg_tid != current_tid:
                if user32.AttachThreadInput(current_tid, fg_tid, True):
                    attached = True
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            if attached:
                user32.AttachThreadInput(current_tid, fg_tid, False)
        except Exception as e:
            plugin_logger.debug(f"设置前台窗口失败: {e}")

    def _active_window(self):
        """特殊模式下若专用窗口已显示则使用它，否则使用主窗口"""
        if (self.backend and self.backend.mode != "normal"
                and self.special_window and self.special_window.isVisible()):
            return self.special_window
        return self.window

    def _is_above_taskbar(self, hwnd=None):
        """检测窗口是否位于任务栏上层（覆盖任务栏）

        任务栏由系统按"前台窗口"动态管理（静态 z 序不可靠）：只有前台
        窗口为全屏置顶窗口时任务栏才会保持在窗口下方。因此判定条件：
        1) 窗口是系统前台窗口（GetForegroundWindow）
        2) 窗口是置顶窗口（WS_EX_TOPMOST）
        3) 窗口矩形覆盖到屏幕底部（任务栏区域）
        三者同时满足才认为 UI 位于任务栏上层、任务栏被其覆盖。
        """
        if sys.platform != 'win32':
            return True
        try:
            user32 = ctypes.windll.user32
            if hwnd is None:
                win = self._active_window()
                if not win:
                    return False
                hwnd = int(win.winId())

            # 1) 必须是系统前台窗口，否则系统会让任务栏浮在其上
            if user32.GetForegroundWindow() != hwnd:
                return False

            # 2) 必须是置顶窗口
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            if not (user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOPMOST):
                return False

            # 3) 必须覆盖到屏幕底部（任务栏所在区域）
            class RECT(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                            ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
            r = RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            screen = QGuiApplication.primaryScreen()
            if screen:
                geo = screen.geometry()
                if r.bottom < geo.y() + geo.height():
                    return False

            return True
        except Exception as e:
            plugin_logger.debug(f"检测任务栏层级失败: {e}")
            return True

    def _force_topmost(self):
        """重新强制窗口置顶并置为前台（Windows），确保全屏模式下覆盖任务栏

        在 QML 全屏过渡/窗口状态切换完成后再调用一次，避免过渡期间
        窗口层级被重置到任务栏之下导致任务栏露出。
        """
        if not self.window or not self.backend:
            return
        if self.backend.mode == "normal":
            return
        if sys.platform != 'win32':
            return
        win = self._active_window()
        if not win:
            return
        try:
            # 先确保 Qt 层窗口标志一致（防止此前被意外清除导致置顶失效）
            if not (win.flags() & Qt.WindowStaysOnTopHint):
                win.setFlag(Qt.WindowStaysOnTopHint, True)
            hwnd = int(win.winId())
            HWND_TOPMOST = -1
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                              SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            win.raise_()
            # 关键：保持前台，否则任务栏会浮在窗口之上
            self._make_foreground_window(hwnd)
        except Exception as e:
            plugin_logger.debug(f"强制置顶失败: {e}")

    def _prepare_special_window(self):
        """按钮按下时即开始创建专用全屏窗口（隐藏，暂不显示）

        立即创建隐藏的专用窗口并加载内容（利用旧窗口播放启动动画的时间作为
        加载时间）；待旧窗口动画播放完成后由 _on_special_animation_finished
        直接显示（无渐变动画），然后隐藏旧窗口。总是刷新 UI。
        """
        if not self.backend or self.backend.mode == "normal":
            return
        if self.special_window or self.special_engine:
            return
        try:
            self.backend.set_switching(True)
            engine = QQmlApplicationEngine()
            engine.rootContext().setContextProperty("lessonsBackend", self.backend)
            # 复制主引擎的导入路径（保证 RinUI 等可用）
            try:
                for p in self.engine.importPathList():
                    engine.addImportPath(p)
            except Exception:
                pass
            qml_path = os.path.join(self.PATH, "qml", "SpecialModeWindow.qml")
            engine.load(QUrl.fromLocalFile(qml_path))
            if not engine.rootObjects():
                plugin_logger.error("创建特殊模式窗口失败：无根对象")
                engine.deleteLater()
                self.backend.set_switching(False)
                return
            win = engine.rootObjects()[0]
            self.special_engine = engine
            self.special_window = win
            # 保持隐藏，等待旧窗口动画完成信号后直接显示
            plugin_logger.info("特殊模式专用窗口已创建（隐藏，等待旧窗口动画完成）")
            # 兜底：即使动画完成信号未触发，也确保专用窗口显示并恢复按钮
            QTimer.singleShot(1500, self._on_special_animation_finished)
            QTimer.singleShot(3000, lambda: self.backend.set_switching(False))
        except Exception as e:
            plugin_logger.error(f"创建特殊模式窗口异常: {e}")
            self._destroy_special_window()
            self.backend.set_switching(False)

    def _on_special_animation_finished(self):
        """旧窗口启动动画播放完成：直接显示专用窗口（无渐变动画），然后隐藏旧窗口"""
        if not self.backend:
            return
        if self.backend.mode == "normal":
            self._destroy_special_window()
            return
        if not self.special_window:
            self.backend.set_switching(False)
            return
        try:
            # 直接显示（无透明度渐变动画），并设为全屏 + 强制置顶 + 设为前台。
            # 注意：QML 中不能写常量 visibility:FullScreen（会导致创建即显示），
            # 因此在此处由 Python 显式设置全屏状态。
            self.special_window.show()
            self.special_window.setWindowState(Qt.WindowFullScreen)
            self._force_topmost()
            # 隐藏旧窗口
            if self.window and self.window is not self.special_window:
                self.window.hide()
            self.backend.set_switching(False)
            plugin_logger.info("特殊模式专用窗口已直接显示，旧窗口已隐藏")
        except Exception as e:
            plugin_logger.error(f"显示特殊模式窗口失败: {e}")
            self.backend.set_switching(False)

    def _destroy_special_window(self):
        """销毁特殊模式专用窗口"""
        if self.special_window:
            try:
                self.special_window.close()
                self.special_window.deleteLater()
            except Exception:
                pass
            self.special_window = None
        if self.special_engine:
            try:
                self.special_engine.deleteLater()
            except Exception:
                pass
            self.special_engine = None
        if self.backend:
            self.backend.set_switching(False)

    def _on_mode_changed(self):
        mode = self.backend.mode
        if mode == "normal":
            # 销毁特殊模式专用窗口并恢复主窗口显示
            self._destroy_special_window()
            if self.window:
                self.window.show()
            self.window.setMask(QRegion())
            self._mask_enabled = False
            self.window.setFlag(Qt.WindowStaysOnTopHint, False)
            if self._cursor_hidden:
                self.window.setCursor(Qt.ArrowCursor)
                self._cursor_hidden = False
            self._cursor_timer.stop()
            if sys.platform == 'win32':
                try:
                    hwnd = int(self.window.winId())
                    HWND_NOTOPMOST = -2
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                                                      SWP_NOMOVE | SWP_NOSIZE)
                except Exception as e:
                    plugin_logger.debug(f"移除系统置顶失败: {e}")
            QTimer.singleShot(400, self._enable_mask_and_update)
        else:
            self.window.setMask(QRegion())
            self._mask_enabled = True
            self.window.setFlag(Qt.WindowStaysOnTopHint, True)
            self._last_mouse_pos = QCursor.pos()
            self._idle_seconds = 0
            self._cursor_hidden = False
            self.window.setCursor(Qt.ArrowCursor)
            self._cursor_timer.start(500)
            if sys.platform == 'win32':
                try:
                    hwnd = int(self.window.winId())
                    HWND_TOPMOST = -1
                    SWP_NOMOVE = 0x0002
                    SWP_NOSIZE = 0x0001
                    ctypes.windll.user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                                      SWP_NOMOVE | SWP_NOSIZE)
                except Exception as e:
                    plugin_logger.debug(f"强制置顶失败: {e}")
            self.window.raise_()
            # QQuickWindow 没有 activateWindow()，须使用 QWindow 的 requestActivate()，
            # 否则每次进入特殊模式都会抛 AttributeError，导致后续延迟置顶不执行
            self.window.requestActivate()
            # 关键：立即把窗口设为系统前台窗口。否则若其它窗口（如资源管理器）
            # 是前台，系统会让任务栏浮在置顶窗口之上（100%复现的露出任务栏问题）。
            self._make_foreground_window(int(self.window.winId()))

            # 延迟再次强制置顶：等待 QML 全屏过渡/窗口状态切换完成后再
            # 重新置顶，确保窗口完全覆盖任务栏（修复偶发露出任务栏问题）。
            # _force_topmost 内部会校验仍处于特殊模式，退出后自动忽略。
            QTimer.singleShot(400, self._force_topmost)
            QTimer.singleShot(1200, self._force_topmost)

            # 按钮按下即开始创建隐藏的专用全屏窗口（利用旧窗口启动动画时间
            # 作为加载时间），旧窗口动画完成后由信号驱动其直接显示并隐藏旧窗口。
            self._prepare_special_window()

    def on_unload(self):
        self._destroy_special_window()
        if self._cursor_timer:
            self._cursor_timer.stop()
            self._cursor_timer.deleteLater()
        if self._scroll_timer:
            self._scroll_timer.stop()
            self._scroll_timer.deleteLater()
        if self._width_timer:
            self._width_timer.stop()
            self._width_timer.deleteLater()
        if self._configs:
            try:
                self._configs.configChanged.disconnect(self._on_config_changed)
            except:
                pass
        if self._layer_timer:
            self._layer_timer.stop()
            self._layer_timer.deleteLater()
        if self._theme_timer:
            self._theme_timer.stop()
            self._theme_timer.deleteLater()
        if self.ui_loader:
            try:
                self.ui_loader.xChanged.disconnect(self._update_mask)
                self.ui_loader.yChanged.disconnect(self._update_mask)
                self.ui_loader.widthChanged.disconnect(self._update_mask)
                self.ui_loader.heightChanged.disconnect(self._update_mask)
            except:
                pass
        if self.window:
            self.window.close()
            self.window.deleteLater()
        if self.engine:
            self.engine.deleteLater()
        plugin_logger.info("今日课程插件卸载")

    def on_runtime_updated(self):
        if self.backend:
            self.backend.update_lessons()

    def on_theme_changed(self, theme_id):
        plugin_logger.debug(f"on_theme_changed 被调用，传入 theme_id: {theme_id}")

    def _update_subjects_map(self):
        entries = self.api.runtime.current_day_entries
        if not entries:
            self._subjects_map = {}
            self._subjects_name_map = {}
            return

        subjects = []
        try:
            schedule = self.api._app.schedule_manager.schedule
            if schedule and hasattr(schedule, 'subjects'):
                subjects = schedule.subjects
        except Exception:
            pass

        if subjects:
            self._subjects_map = {}
            self._subjects_name_map = {}
            for subj in subjects:
                abbr = subj.simplifiedName or (subj.name[0] if subj.name else "?")
                self._subjects_map[subj.id] = abbr
                self._subjects_name_map[subj.id] = subj.name
        else:
            self._subjects_map = {}
            self._subjects_name_map = {}

    def _get_entry_abbr(self, entry):
        subject_id = entry.get("subjectId")
        if subject_id and subject_id in self._subjects_map:
            return self._subjects_map[subject_id]

        title = entry.get("title", "")
        if title:
            return title[0] if title else "?"

        entry_type = entry.get("type", "")
        if entry_type == "break":
            return "休"
        elif entry_type == "activity":
            return "活"
        elif entry_type == "preparation":
            return "预"
        else:
            return "?"