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


class LessonsBackend(QObject):
    lessonsUpdated = Signal()
    themeChanged = Signal(bool)
    positionChanged = Signal()
    widthChanged = Signal()
    scrollRequested = Signal(int)  # 请求滚动到指定索引

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin
        self._lessons = []
        self._current_lesson_id = ""
        self._next_lesson_id = ""
        self._current_state = 0
        self._is_dark = False
        self._ui_x = 0
        self._ui_y = 0
        self._ui_width = DEFAULT_UI_WIDTH

    def update_lessons(self):
        entries = self.plugin.api.runtime.current_day_entries
        if not entries:
            self._lessons = []
            self._current_lesson_id = ""
            self._next_lesson_id = ""
            self.lessonsUpdated.emit()
            return

        self.plugin._update_subjects_map()

        lessons = []
        filtered_ids = set()
        for entry in entries:
            entry_id = entry.get("id", "")
            entry_type = entry.get("type", "")
            title = entry.get("title", "")
            # 排除规则：课间和特定活动
            if entry_type == "break":
                continue
            if entry_type == "activity" and title in ["大课间", "升旗"]:
                continue
            abbr = self.plugin._get_entry_abbr(entry)
            is_class = (entry_type == "class")
            lessons.append({
                "id": entry_id,
                "abbr": abbr,
                "isClass": is_class
            })
            filtered_ids.add(entry_id)
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
            anchor = prefs.widgets_anchor
            offset_x = prefs.widgets_offset_x
            offset_y = prefs.widgets_offset_y

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
                    y = 108 + offset_y
                elif vert == "bottom":
                    y = screen_height - UI_HEIGHT - offset_y - 60
                else:
                    y = 132

                if horz == "center":
                    x = (screen_width - ui_width) // 2 + offset_x
                elif horz == "left":
                    x = offset_x
                elif horz == "right":
                    x = screen_width - ui_width - offset_x
                else:
                    x = (screen_width - ui_width) // 2

            self._ui_x = int(x)
            self._ui_y = int(y)
            self.positionChanged.emit()
        except Exception as e:
            plugin_logger.error(f"计算位置失败: {e}")
            screen = QGuiApplication.primaryScreen().availableGeometry()
            self._ui_x = (screen.width() - self._ui_width) // 2
            self._ui_y = 132
            self.positionChanged.emit()

    def request_scroll_to_current(self):
        """请求将当前高亮课程滚动到视野内"""
        target_id = self._current_lesson_id or self._next_lesson_id
        if not target_id:
            return
        for i, lesson in enumerate(self._lessons):
            if lesson["id"] == target_id:
                self.scrollRequested.emit(i)
                break

    @Property(int, notify=positionChanged)
    def uiX(self):
        return self._ui_x

    @Property(int, notify=positionChanged)
    def uiY(self):
        return self._ui_y

    @Property(int, notify=widthChanged)
    def uiWidth(self):
        return self._ui_width

    @Property(list, notify=lessonsUpdated)
    def lessons(self):
        return self._lessons

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


class Plugin(CW2Plugin):
    def __init__(self, api):
        super().__init__(api)
        self._subjects_map = {}
        self.backend = None
        self.is_dark_theme = False
        self.engine = None
        self.window = None
        self.ui_item = None
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
        self._start_scroll_timer()  # 启动滚动定时器

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
        if not self.window or not self.ui_item:
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
        """启动每秒滚动请求定时器"""
        self._scroll_timer = QTimer()
        self._scroll_timer.timeout.connect(self._request_scroll)
        self._scroll_timer.start(1000)
        plugin_logger.debug("已启动滚动请求定时器")

    def _request_scroll(self):
        """请求滚动到当前高亮课程"""
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

            self.ui_item = loader.property("item")
            if not self.ui_item:
                plugin_logger.error("UI 项未加载")
                return

            x = self.ui_item.x()
            y = self.ui_item.y()
            w = self.ui_item.width()
            h = self.ui_item.height()
            plugin_logger.debug(f"UI 项初始位置: ({x}, {y}, {w}, {h})")

            self.ui_item.widthChanged.connect(self._update_mask)
            self.ui_item.heightChanged.connect(self._update_mask)
            self.ui_item.xChanged.connect(self._update_mask)
            self.ui_item.yChanged.connect(self._update_mask)

            self._update_mask()

            self.window.show()
            plugin_logger.info("窗口已显示")

            self._sync_window_layer()
            self._start_width_polling()
            # 滚动定时器已在 on_load 中启动，此处不需要重复启动

            plugin_logger.info("UI 已加载，mask 更新连接已建立")
        except Exception as e:
            plugin_logger.error(f"处理 UI 就绪失败: {e}")

    def _update_mask(self):
        if not self.window or not self.ui_item:
            return
        try:
            x = int(self.ui_item.x())
            y = int(self.ui_item.y())
            w = int(self.ui_item.width())
            h = int(self.ui_item.height())
            region = QRegion(x, y, w, h)
            self.window.setMask(region)
        except Exception as e:
            plugin_logger.error(f"更新 mask 失败: {e}")

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
        if self.ui_item:
            try:
                self.ui_item.widthChanged.disconnect(self._update_mask)
                self.ui_item.heightChanged.disconnect(self._update_mask)
                self.ui_item.xChanged.disconnect(self._update_mask)
                self.ui_item.yChanged.disconnect(self._update_mask)
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
            for subj in subjects:
                abbr = subj.simplifiedName or (subj.name[0] if subj.name else "?")
                self._subjects_map[subj.id] = abbr
        else:
            subject_ids = set()
            for entry in entries:
                subj_id = entry.get("subjectId")
                if subj_id:
                    subject_ids.add(subj_id)
            self._subjects_map = {sid: "?" for sid in subject_ids}

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