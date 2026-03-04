"""
Class Widgets 2.0 - 今日课程显示插件 (独立全屏窗口版)
显示当日所有课程缩写，并高亮当前课程，使用mask仅显示UI区域
"""

import os
import darkdetect
from loguru import logger
from PySide6.QtCore import QObject, QUrl, Slot, Property, Signal, QTimer
from PySide6.QtGui import QGuiApplication, QScreen, QRegion
from PySide6.QtQml import QQmlApplicationEngine
from ClassWidgets.SDK import CW2Plugin
from PySide6.QtCore import Qt

plugin_logger = logger.bind(plugin="lessons-displayer")

# 默认宽度常量
DEFAULT_UI_WIDTH = 100
UI_HEIGHT = 54


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

    def set_ui_opacity(self, opacity):
        if opacity != self._opacity:
            self._opacity = opacity
            self.opacityChanged.emit()

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
            self._display_items = []
            self._current_lesson_id = ""
            self._next_lesson_id = ""
            self.lessonsUpdated.emit()
            return

        self.plugin._update_subjects_map()

        all_entries = entries
        n = len(all_entries)

        def should_show(entry):
            e_type = entry.get("type", "")
            if e_type == "break":
                return False
            if e_type == "activity" and entry.get("title") in ["大课间", "升旗"]:
                return False
            return True

        show_flags = [should_show(e) for e in all_entries]

        display_items = []
        lessons = []
        filtered_ids = set()

        for i, entry in enumerate(all_entries):
            if not show_flags[i]:
                continue

            entry_id = entry.get("id", "")
            entry_type = entry.get("type", "")
            title = entry.get("title", "")
            abbr = self.plugin._get_entry_abbr(entry)
            full_name = self._get_entry_full_name(entry)
            is_class = (entry_type == "class")

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

            if i < n - 1:
                next_entry = all_entries[i + 1]
                if show_flags[i + 1]:
                    current_end = _time_to_minutes(entry.get("endTime"))
                    next_start = _time_to_minutes(next_entry.get("startTime"))
                    gap = next_start - current_end
                    if gap >= 15:
                        display_items.append({"type": "separator"})

        self._display_items = display_items
        self._lessons = lessons

        # 更新当前课程ID（只考虑课程）
        current = self.plugin.api.runtime.current_entry
        if current and current.get("type") == "class":
            self._current_lesson_id = current.get("id", "")
        else:
            self._current_lesson_id = ""

        # 更新下一节课ID
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

        # 更新当前图标和剩余时间文本
        self._update_current_icon_and_remaining()

    def _update_current_icon_and_remaining(self):
        """更新当前活动的图标和剩余时间文本"""
        current_entry = self.plugin.api.runtime.current_entry
        if not current_entry:
            self._current_icon = "ic_fluent_question_20_regular"
            self._current_remaining_text = ""
            return

        # 确定图标
        subject_id = current_entry.get("subjectId")
        icon_found = False
        if subject_id:
            try:
                schedule = self.plugin.api._app.schedule_manager.schedule
                if schedule and hasattr(schedule, 'subjects'):
                    for subj in schedule.subjects:
                        if subj.id == subject_id and subj.icon:
                            self._current_icon = subj.icon
                            icon_found = True
                            break
            except Exception as e:
                plugin_logger.debug(f"获取科目图标失败: {e}")

        if not icon_found:
            # 无科目或未找到，根据类型使用默认图标
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

        # 计算剩余时间文本
        remaining = self.plugin.api.runtime.remaining_time
        if not remaining:
            self._current_remaining_text = ""
            return

        minutes = remaining.get("minute", 0)
        seconds = remaining.get("second", 0)
        total_seconds = minutes * 60 + seconds

        if total_seconds < 60:
            secs = max(1, total_seconds)
            if self._current_state == 1:  # 上课
                self._current_remaining_text = f"剩 {secs} 秒"
            else:  # 课间
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
                        y = 108 + offset_y
                elif vert == "bottom":
                    if hide and horz == "center":
                        y = screen_height - 24
                    else:
                        y = screen_height - UI_HEIGHT - offset_y - 60
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


class Plugin(CW2Plugin):
    def __init__(self, api):
        super().__init__(api)
        self._subjects_map = {}
        self._subjects_name_map = {}  # 新增：科目ID到全名的映射
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

            QTimer.singleShot(5000, self._check_ui_ready_timeout)

            plugin_logger.info("全屏窗口已创建（隐藏状态）")
        else:
            plugin_logger.error("无法创建全屏窗口")

        self._start_theme_polling()
        self._start_layer_sync()
        self._start_scroll_timer()

    def _on_config_changed(self):
        plugin_logger.debug("配置变化，更新位置")
        if self.backend:
            self.backend.update_position()

    def _start_layer_sync(self):
        self._layer_timer = QTimer()
        self._layer_timer.timeout.connect(self._sync_window_layer)
        self._layer_timer.start(1000)
        plugin_logger.debug("已启动窗口层级同步定时器")

    def _sync_window_layer(self):
        if not self.window or not self.backend:
            return
        if self.backend.mode != "normal":
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

    def _on_mode_changed(self):
        mode = self.backend.mode
        if mode == "normal":
            self.window.setMask(QRegion())
            self._update_mask()
        else:
            self.window.setMask(QRegion())
            self.window.raise_()
            self.window.activateWindow()

    def on_unload(self):
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